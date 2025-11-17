"""'
ADCS controller service
"""

import socket
from queue import SimpleQueue

from olaf import Gpio, Service, logger

import numpy as np
from skyfield.api import load
from scipy.linalg import solve_discrete_are
from scipy.signal import cont2discrete 
from Kalman_Filter import Multiplicative_Extended_Kalman_Filter


class ADCS_FlightSoftware(Service):
    def __init__(self, mock_hw: bool = False):
        super().__init__()
        
        config = None # TEMPORARY PLACE HOLDER TO GET RID OF LINTING ERRORS
        
        self.mission_mode = None # select control mode. Modes are "POINTING", "TRACKING", "DETUMBLE", "THERMAL_DETUMBLE", "THERMAL_REORIENT", and "THERMAL_SPINUP"
        self.pointing_reference = None # select reference payload (i.e. Selfie Cam or Cirrus Flux Camera). Modes are "SC" and "CFC" 
        self.q_target = None # target quaternion for controller error calculations
        self.tracking_target = None # used for tracking mode to set static target with GPS coordinates
        
        self.G = config["G"] # wheel orientation matrix
        self.G_transpose = self.G.T # transpose of wheel orientation matrix
        self.G_pinv = -np.linalg.pinv(self.G) # pseudo inverse matrix for torque calculations. NEGATE OR NOT????
        self.q_90_rot = self.axis_angle_to_quaternion([0,1,0], -90) # translate star tracker targets to +z side of satellite
        self.q_180_rot = self.axis_angle_to_quaternion([0,1,0], -180) # translate CFC targets to +z side/viewpoint of satellite
        
        max_input = 0.00003 # qualitative value for max torque used by LQR tuning only, not actual torque limit of reaction wheel
        LQR_max_error = 0.01 # qualitative value
        LQR_max_rate = 0.002 # qualitative value
        self.K_RW = self.get_RW_gain_matrix(self.satInertia, self.updateTime, LQR_max_error, LQR_max_rate, max_input) # calculate reaction wheel LQR gain matrix
        self.EKF = Multiplicative_Extended_Kalman_Filter(config["P_ST_0"], config["sigma_ST"], config["P_b0"], config["sigma_gyro"], config["sigma_bias"])

        self.skyfield_timescale = load.timescale()
        self.skyfield_ephemeris = load('de440s.bsp') # UPDATE THIS TO POINT TO ACTUAL FILE
        
    def on_start(self):
        # INITIALIZE FILTER WITH STAR TRACKER AND IMU DATA IF USING REACTION WHEELS
        # self.EKF.q = q # initialize filter
        # self.EKF.last_omega = omega
        pass

    def on_loop(self, currentTimeNanos):
        omega = None # GET GYRO DATA omega required for all controllers. Maybe move this? How will data transfer checks work? How will I know if a piece of data is available?
        
        if (self.mission_mode == "POINTING") or (self.mission_mode == "THERMAL_REORIENT"):
            if star_tracker_available:
                q_star_tracker = None # GET STAR TRACKER
                q_star_tracker = self.to_scalar_last(q_star_tracker) # convert star tracker to scalar-last format, if
                q_st_rotated = self.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None
            if not gyro_available:
                omega = None
            q, omega = self.EKF.update(currentTimeNanos*1e-9, omega, q_st_rotated) # update filter with applicable data
                
            q_error = self.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = self.hemi(q_error) # only apply hemisphere check once after determining error quaternion to maintain associativity across hermisphere boundaries
            
            desired_torque = self.quaternion_controller(q_error, omega) # compute desired 3-axis torque from controller
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            # COMMAND REACTION WHEELS
            
            if (self.mission_mode == "THERMAL_REORIENT") and (self.error_angle(q_error) <= 0.1) and (np.all(np.abs(omega) < 1e-6)):
                # ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS!
                self.mission_mode = "THERMAL_SPINUP"
        
        elif self.mission_mode == "TRACKING": # separate from POINTING mode as tracking requires use of feedforward terms
            # GET WHEELS SPEEDS    
            
            if star_tracker_available:
                q_star_tracker = None # GET STAR TRACKER
                q_star_tracker = self.to_scalar_last(q_star_tracker) # convert star tracker to scalar-last format, if
                q_st_rotated = self.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None
            if not gyro_available:
                omega = None
            q, omega = self.EKF.update(currentTimeNanos*1e-9, omega, q_st_rotated) # update filter with applicable data
            
            q_last = self.q_target # save last target for feed-forward terms
            self.update_tracking_target() # update target orientation based on current orientation and fixed target
            
            q_error = self.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = self.hemi(q_error) # only apply hemisphere check once after determining error quaternion to maintain associativity across hermisphere boundaries
        
            # feed forward term for angular rate bias
            rotation_quat = self.quat_error(q_last, self.q_target) # flipped order because of frame conventions for proper signage (body -> target)
            rot_axis = self.quat_to_axis(rotation_quat)
            rot_angle = self.error_angle(rotation_quat) * np.pi/180
            omega_desired = rot_axis*(rot_angle/self.updateTime) # set rotation rate for tracking maneuver
            
            # feed forward term for stored angular momentum
            alpha_d_B = (omega_desired - self.omega_desired_prev) / self.updateTime # desired acceleration in body frame
            self.omega_desired_prev = omega_desired.copy() # update previous target rate
            H_wheels = self.rwInertia * wheelSpeeds @ self.G.T # calculate stored wheel momentum in body frame
            tau_ff = self.satInertia @ alpha_d_B + np.cross(omega, self.satInertia @ omega + H_wheels) # total feed-forward torque accounting for gyroscopic coupling
        
            omega = omega-omega_desired # set biased omega after using true value to calculate feed forward term
            
            desired_torque = self.quaternion_controller(q_error, omega) # compute desired 3-axis torque from controller
            desired_torque = desired_torque+tau_ff
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            # COMMAND REACTION WHEELS
        
        elif ((self.mission_mode == "DETUMBLE") or (self.mission_mode == "THERMAL_DETUMBLE")): # enter 3-step passive thermal-spin mode by first detumbling with magnetorquers
            B = None # GET MAG DATA
            desired_torque = self.detumble_gain/(np.linalg.norm(B)**2)*np.cross(omega, B) # detumble controller as defined by Markley & Crassidis
            # COMMAND MAGNETORQUERS 
            
            if ((self.mission_mode == "THERMAL_DETUMBLE") and (np.all(np.abs(omega) < 1e-4))): # if using 3-step passive thermal-spin controller, check for 
                self.mission_mode = "THERMAL_REORIENT"
                # INITIALIZE FILTER WITH STAR TRACKER AND IMU DATA
                # self.EKF.q = q # initialize filter
                # self.EKF.last_omega = omega
        
        elif self.mission_mode == "THERMAL_SPINUP": # spin up about satellite's z-axis using magnetorquer
            if (omega[2] < self.thermal_spin_rpm*2*np.pi/60): # while satellite is spinning slower than set rate about the z axis, spin up
                B = None # GET MAG DATA
                tau_des = [0,0,1] # spin about the z axis
                desired_torque = np.cross(B, tau_des) / (B @ B)
                # COMMAND MAGNETORQUERS
                
            # Should we add exit clause? How would we shut down adcs with a flag?
        
        else:
            print("Unknown mission mode!")
    
    def quaternion_controller(self, q_error, omega):
        x = np.concatenate((q_error[:3], omega)) # assemble state vector
        return -self.K_RW @ x # invert sign for control
    
    def quat_conjugate(self, q):
        q1, q2, q3, qs = q
        return [-q1, -q2, -q3, qs]

    def hemi(self, q):
        q = np.asarray(q, dtype=float)
        return q if q[3] >= 0 else -q # if scalar part negative negate entire quaternion

    def normalize(self, q):
        q = np.asarray(q, dtype=float)
        return q / np.linalg.norm(q)

    def quat_mult(self, q_rot, q_init): # Shuster quaternion multiplication
        x1, y1, z1, s1 = q_rot
        x2, y2, z2, s2 = q_init
        
        q_new = [
            s1*x2 + x1*s2 - y1*z2 + z1*y2,
            s1*y2 + y1*s2 - z1*x2 + x1*z2,
            s1*z2 + z1*s2 - x1*y2 + y1*x2,
            s1*s2 - x1*x2 - y1*y2 - z1*z2
        ]
        return self.normalize(q_new)

    def quat_error(self, q_target, q_current): # error defined by Markley & Crassidis.
        return self.quat_mult(q_current, self.quat_conjugate(q_target)) # returns normalized quaternion. Sanitization happens in quat_mult function

    def to_scalar_last(self, q): # convert quaternion to scalar-last convention
        return np.concatenate((q[1:], [q[0]]))

    def axis_angle_to_quaternion(self, axis, angle_deg):
        angle_rad = np.radians(angle_deg)
        u = np.array(axis) / np.linalg.norm(axis)
        q_vec = u * np.sin(angle_rad / 2)
        q_scalar = np.cos(angle_rad / 2)
        q = np.concatenate((q_vec, [q_scalar])) # create scalar-last quaternion 
        q = q/np.linalg.norm(q) # normalize quaternion to account for numerical errors
        return q

    def quat_to_axis(self, q_error): # returns axis of rotation
        q = q_error / np.linalg.norm(q_error)
        w = q[3]
        sin_half_angle = np.sqrt(1 - w**2)
        if sin_half_angle < 1e-6:
            axis = np.array([1.0, 0.0, 0.0])  # default axis
        else:
            axis = q[:3] / sin_half_angle
        return axis

    def error_angle(self, q_error):
        """
        Returns the error angle in degrees based on error quaternion
        """
        
        return 2*np.acos(abs(q_error[3])) * 180/ np.pi
    
    def get_RW_gain_matrix(self, J, timestep, max_error, max_rate, max_input, use_integrator = False):
        #----------------- LQR matrices--------------------------------------------
        max_error = max_error # q_vec error
        max_velocity = max_rate # ω_sat
        max_integrator = 0.1 # integrator term in Q matrix, integrator state, accumulated error (shouldnt exceed Q values for quaternion error)
        
        Q = np.diag([1/max_error**2, 1/max_error**2, 1/max_error**2, 1/max_velocity**2, 1/max_velocity**2, 1/max_velocity**2, 1/max_integrator**2, 1/max_integrator**2, 1/max_integrator**2])
        R = np.diag([1/max_input**2, 1/max_input**2, 1/max_input**2])
        #--------------------------------------------------------------------------
        '''
        When using the left-error quaternion convention, meaning q_error = q_target * q_current^-1,
        the derivative of the error quaternion is negative, so A becomes negative. Currently using the right-handed convention
        so A is positive.
        '''
        A = 0.5*np.eye(6, 6, 3) # A matrix: maps ω into q_dot, ω_dot is driven by control input (J^{-1} u). 
        B = np.block([[np.zeros((3,3))], [np.linalg.inv(J)]])
        C = np.identity(6) # sensors for all inputs
        D = np.zeros((C.shape[0], B.shape[1]))
        
        Ad, Bd, Cd, Dd, dt = cont2discrete((A, B, C, D), timestep)
        P = solve_discrete_are(Ad, Bd, Q[:6, :6], R)
        K = np.linalg.inv(R+Bd.T @ P @ Bd) @ Bd.T @ P @ Ad
        
        A_cl = Ad - Bd @ K  # Discrete closed-loop matrix
        eigvals = np.linalg.eigvals(A_cl)
        
        for i, eig in enumerate(eigvals):
            # print(f"Eigenvalue {i}: {eig}  | Magnitude: {abs(eig)}")
            if abs(eig) > 1:
                print("WARNING: EIGENVALUE OUTSIDE OF UNIT CIRCLE")
        
        return K
    
    def update_target(self, target_quat): # UPDATE THIS FUNCTION TO USE POINTING REFERENCE AS AN ARGUMENT???
        if self.pointing == "ST":
            self.q_target = self.quat_mult(self.q_90_rot, target_quat) # define target in body coordinates
        elif self.pointing == "SC":
            self.q_target = target_quat # target does not require rotation
        elif self.pointing == "CFC":
            self.q_target = self.quat_mult(self.q_180_rot, target_quat) # define target in body coordinates
    
    def update_tracking_target(self): # function for tracking a static target during overpasses
        pass
    
    def get_sun_vector(self, time): # determines and sets sun vector as target
        t = self.ts.utc(2025, 11, 6) # REPLACE THIS WITH REAL TIME INPUT
        earth, sun = self.skyfield_ephemeris['earth'], self.skyfield_ephemeris['sun']
        r_es_km = earth.at(t).observe(sun).position.km   # Earth→Sun vector in ECI
        s_hat   = r_es_km / np.linalg.norm(r_es_km)      # unit vector in ECI pointing towards sun
        
        x_B_N, y_B_N, z_B_N = self.build_sun_pointing_frame(s_hat) # build coordinate system (triad) with +x pointing towards sun and +z perpendicular to sun vector
        C_BN = self.dcm_BN_from_body_axes(x_B_N, y_B_N, z_B_N)
        q_BN_target = self.quat_from_dcm_scalar_last(C_BN) # create target quaternion from 
        self.update_target(q_BN_target) # udpate target (SHOULD WE CHANGE THIS TO PASS IN TARGET AS ARGUMENT???)
    
    def build_sun_pointing_frame(s_N, eps=1e-8):
        """
        Given Sun direction s_N (unit vector, inertial) build body axes,
        expressed in inertial frame to later be passed into DCM creation function:
            x_B_N points toward sun
            z_B_N is perpendicular to sun
            y_B_N completes right-handed rule
        """
        
        ref_N = np.array([0.0, 0.0, 1.0]) # Choose some reference inertial vector not parallel to s_N
        if abs(np.dot(ref_N, s_N)) > 1.0 - eps: # If ref_N is nearly parallel to s_N, pick a different reference vector
            ref_N = np.array([0.0, 1.0, 0.0])
            
        x_B_N = s_N # x_B points to Sun
    
        # z_B is ref_N projected into the plane perpendicular to s_N
        ref_N = ref_N / np.linalg.norm(ref_N)
        z_B_N = ref_N - np.dot(ref_N, s_N) * s_N # remove component of ref_N perpendicular to s_N
        z_B_N = z_B_N / np.linalg.norm(z_B_N)
    
        # y_B completes right-handed system
        y_B_N = np.cross(z_B_N, x_B_N)
        y_B_N = y_B_N / np.linalg.norm(y_B_N)
    
        return x_B_N, y_B_N, z_B_N
    
    def dcm_BN_from_body_axes(x_B_N, y_B_N, z_B_N): # build a DCM from triad
        C_BN = np.column_stack((x_B_N, y_B_N, z_B_N))
        return C_BN
    
    def quat_from_dcm_scalar_last(self, C_BN):
        """
        C_BN: DCM mapping inertial → body using numerically stable methods which
        avoid singularities and square roots of negative values
        Returns scalar-last quaternion
        
        qw represents scalar component of quaternion, as s is already used as
        intermediate variable
        """
        m = C_BN
        trace = np.trace(m)
    
        if trace > 0.0: # if trace is greater than zero, start with scalar component
            s = 0.5 / np.sqrt(trace + 1.0)
            qw = 0.25 / s
            qx = (m[2,1] - m[1,2]) * s
            qy = (m[0,2] - m[2,0]) * s
            qz = (m[1,0] - m[0,1]) * s
        else:
            if m[0,0] > m[1,1] and m[0,0] > m[2,2]:
                s = 2.0 * np.sqrt(1.0 + m[0,0] - m[1,1] - m[2,2])
                qw = (m[2,1] - m[1,2]) / s
                qx = 0.25 * s
                qy = (m[0,1] + m[1,0]) / s
                qz = (m[0,2] + m[2,0]) / s
            elif m[1,1] > m[2,2]:
                s = 2.0 * np.sqrt(1.0 + m[1,1] - m[0,0] - m[2,2])
                qw = (m[0,2] - m[2,0]) / s
                qx = (m[0,1] + m[1,0]) / s
                qy = 0.25 * s
                qz = (m[1,2] + m[2,1]) / s
            else:
                s = 2.0 * np.sqrt(1.0 + m[2,2] - m[0,0] - m[1,1])
                qw = (m[1,0] - m[0,1]) / s
                qx = (m[0,2] + m[2,0]) / s
                qy = (m[1,2] + m[2,1]) / s
                qz = 0.25 * s
    
        q = np.array([qx, qy, qz, qw])
        q = q / np.linalg.norm(q)
        return q