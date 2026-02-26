"""'
ADCS controller service
"""

import socket
from queue import SimpleQueue

from olaf import Gpio, Service, logger

import numpy as np
import Quaternions as quat
from skyfield.api import load
from skyfield.framelib import itrs

# Custom GNC/ADCS functions
from ADCS_Discrete_State_Space_Calculator import get_gain_matrix
from Kalman_Filter import Multiplicative_Extended_Kalman_Filter
import Quaternions as quat
import Guidance_Functions as guid


class ADCS_FlightSoftware(Service):
    def __init__(self, mock_hw: bool = False):
        super().__init__()
        
        config = None # TEMPORARY PLACE HOLDER TO GET RID OF LINTING ERRORS
        
        self.mission_mode = None # select control mode. Modes are "POINTING", "TRACKING", "DETUMBLE", "THERMAL_DETUMBLE", "THERMAL_REORIENT", and "THERMAL_SPINUP"
        self.pointing_reference = None # select reference payload (i.e. Selfie Cam or Cirrus Flux Camera). Modes are "SC" and "CFC" 
        self.q_target = None # target quaternion for controller error calculations
        self.tracking_target = None # used for tracking mode to set static target with GPS coordinates
        
        self.G = config["G"] # wheel orientation matrix
        self.G_transpose = self.G.T # save repeated calculations each iteration
        self.G_pinv = -np.linalg.pinv(self.G) # pseudo inverse matrix for torque calculations. NEGATE OR NOT????
        self.q_90_rot = self.axis_angle_to_quaternion([0,1,0], -90) # translate star tracker targets to +z side of satellite
        self.q_180_rot = self.axis_angle_to_quaternion([0,1,0], -180) # translate CFC targets to +z side/viewpoint of satellite
        
        self.q_target = np.array([0,0,0,1]) # attribute initialization, set to real value in sim main
        omega_target_rpm = np.array([0.0, 0.0, 0.0]) # [RPM]
        self.omega_target = omega_target_rpm * 2*np.pi/60 # convert to [rad/s]
        
        # Controller gains        
        max_input = 0.00001 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error = 0.01
        LQR_max_rate = 0.002
        self.K_RW = get_gain_matrix(self.satInertia, self.updateTime, LQR_max_error, LQR_max_rate, max_input) # calculate reaction wheel LQR gain matrix
        
        max_input_mag = 0.3 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error_mag = 0.05
        LQR_max_rate_mag = 0.00003
        self.K_MAG = get_gain_matrix(self.satInertia, self.updateTime, LQR_max_error_mag, LQR_max_rate_mag, max_input_mag)
        
        # Controller gains
        Jmin = np.min(np.linalg.eigvals(self.satInertia)) # maximum principal moment of inertia (Markley & Crassidis defines this with the minimum principal moment of inertia, but maximum works better???)
        self.detumble_gain = 4*np.pi/config["orbital_period"]*(1+np.sin(config["orbital_inclination"]*2*np.pi/180))*Jmin # gain based on minimal principal moment of inertia as defined in Markley & Crassidis
        
        # Kalman Filter
        self.EKF = Multiplicative_Extended_Kalman_Filter(config["P_ST_0"], config["sigma_ST"], config["P_b0"], config["sigma_gyro"], config["sigma_bias"])

        self.skyfield_timescale = load.timescale()
        self.skyfield_EOP = itrs # Earth Orientation Parameters  UPDATE THIS TO POINT TO ACTUAL FILE || IMPORTANT TO UPDATE, SENSITIVE TO ERRORS OVER TIME
        
        # self.maxTorque = 0.01 # maximum torque output of reaction wheel [Nm]
        self.maxTorque = 0.001 # maximum torque output of reaction wheel [Nm]
        self.thermal_spin_rpm = 1.0 # thermal spin rate about the z-axis (body frame)
        self.omega_desired_prev = np.zeros(3) # for feed forward term
        
    def on_start(self):
        # initialize filter with star tracker and gyro data if using one of the reaction wheel mode
        if (self.mission_mode == "POINTING") or (self.mission_mode == "THERMAL_REORIENT") or (self.mission_mode == "TRACKING"):
            omega = self.node.od['adcs']['IMU']
            q = self.node.od['adcs']['star_tracker']
            init_time = self.node.od['adcs']['gps_timestamp']
            self.EKF.reset(q, omega, init_time) # reset filter states for next maneuver CHECK IF STAR TRACKER WAS AVAILABLE

    def on_loop(self, currentTimeNanos):
        # omega = self.node.od['adcs']['omega'] # Get gyro data. Omega required for all controllers. Maybe move this? How will data transfer checks work? How will I know if a piece of data is available?
        # t_omega = self.node.od['adcs']['t_omega'] # Get gyro read time
        
        if (self.mission_mode == "POINTING") or (self.mission_mode == "TRACKING") or (self.mission_mode == "THERMAL_REORIENT"):
            wheelSpeeds = self.node.od['adcs']['RW_speeds'] # get reaction wheel speeds

            if star_tracker_available:
                q_star_tracker = self.node.od['star_tracker'] # GET STAR TRACKER
                q_star_tracker = quat.to_scalar_last(q_star_tracker) # convert star tracker to scalar-last format, if
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None
            if gyro_available:
                omega = None
            else:
                omega = self.node.od['adcs']['IMU']
            
            q, omega = self.EKF.update(currentTimeNanos*1e-9, omega, q_st_rotated) # update filter with applicable data
            q, omega = self.EKF.q, self.EKF.omega # get current state estimates from kalman filter
            
            q_error = quat.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = quat.hemi(q_error) # only apply hemisphere check once after determining error quaternion to maintain associativity across hermisphere boundaries
            
            desired_torque = quat.quaternion_controller(q_error, omega) # compute desired 3-axis torque from controller
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            # COMMAND REACTION WHEELS
            
            if (self.mission_mode == "THERMAL_REORIENT") and (self.error_angle(q_error) <= 0.1) and (np.all(np.abs(omega) < 1e-6)):
                # ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS!
                self.mission_mode = "THERMAL_SPINUP"
        
        elif self.mission_mode == "TRACKING": # separate from POINTING mode as tracking requires use of feedforward terms
            wheelSpeeds = self.node.od['adcs']['RW_speeds'] # get reaction wheel speeds
            
            # if star_tracker_available:
            #     q_star_tracker = None # GET STAR TRACKER
            #     q_star_tracker = self.to_scalar_last(q_star_tracker) # convert star tracker to scalar-last format, if
            #     q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker)
            # else:
            #     q_st_rotated = None
            # if not gyro_available:
            #     omega = None
            # q, omega = self.EKF.update(currentTimeNanos*1e-9, omega, q_st_rotated) # update filter with applicable data
            
            q, omega = self.EKF.q, self.EKF.omega # get current state estimates from kalman filter
            
            q_last = self.q_target # save last target for feed-forward terms
            self.update_tracking_quat() # update target orientation based on current orientation and fixed target
            
            q_error = quat.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = quat.hemi(q_error) # only apply hemisphere check once after determining error quaternion to maintain associativity across hermisphere boundaries
        
            # feed forward term for angular rate bias
            rotation_quat = quat.quat_error(q_last, self.q_target) # flipped order because of frame conventions for proper signage (body -> target)
            rot_axis = quat.quat_to_axis(rotation_quat)
            rot_angle = quat.error_angle(rotation_quat) * np.pi/180
            omega_desired = rot_axis*(rot_angle/self.updateTime) # set rotation rate for tracking maneuver
            
            # feed forward term for stored angular momentum
            alpha_d_B = (omega_desired - self.omega_desired_prev) / self.updateTime # desired acceleration in body frame
            self.omega_desired_prev = omega_desired.copy() # update previous target rate
            H_wheels = self.rwInertia * wheelSpeeds @ self.G_transpose # calculate stored wheel momentum in body frame
            tau_ff = self.satInertia @ alpha_d_B + np.cross(omega, self.satInertia @ omega + H_wheels) # total feed-forward torque accounting for gyroscopic coupling
        
            omega = omega-omega_desired # set biased omega after using true value to calculate feed forward term
            
            desired_torque = self.quaternion_controller(q_error, omega) # compute desired 3-axis torque from controller
            desired_torque = desired_torque+tau_ff
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            
            # COMMAND REACTION WHEELS
        
        elif ((self.mission_mode == "DETUMBLE") or (self.mission_mode == "THERMAL_DETUMBLE")): # enter 3-step passive thermal-spin mode by first detumbling with magnetorquers
            omega = self.node.od['adcs']['omega'] # get gyro data
            B = omega = self.node.od['adcs']['magnetometer'] # get magnetometer data
            desired_torque = self.detumble_gain/(np.linalg.norm(B)**2)*np.cross(omega, B) # detumble controller as defined by Markley & Crassidis
            # COMMAND MAGNETORQUERS 
            
            if ((self.mission_mode == "THERMAL_DETUMBLE") and (np.all(np.abs(omega) < 1e-4))): # if using 3-step passive thermal-spin controller, check for 
                self.mission_mode = "THERMAL_REORIENT"
                # INITIALIZE FILTER WITH STAR TRACKER AND IMU DATA
                # self.EKF.q = q # initialize filter
                # self.EKF.last_omega = omega
        
        elif self.mission_mode == "THERMAL_SPINUP": # spin up about satellite's z-axis using magnetorquer
            omega = self.node.od['adcs']['omega'] # get gyro data
            if (omega[2] < self.thermal_spin_rpm*2*np.pi/60): # while satellite is spinning slower than set rate about the z axis, spin up
                B = omega = self.node.od['adcs']['magnetometer'] # get magnetometer data
                tau_des = [0,0,1] # spin about the z axis
                desired_torque = np.cross(B, tau_des) / (B @ B)
                # COMMAND MAGNETORQUERS
                
            # Should we add exit clause? How would we shut down adcs with a flag?
        
        else:
            print("Unknown mission mode!")
    
    def update_target(self, target_quat): # UPDATE THIS FUNCTION TO USE POINTING REFERENCE AS AN ARGUMENT???
        if self.pointing == "ST":
            self.q_target = quat.quat_mult(self.q_90_rot, target_quat) # define target in body coordinates
        elif self.pointing == "SC":
            self.q_target = target_quat # target does not require rotation
        elif self.pointing == "CFC":
            self.q_target = quat.quat_mult(self.q_180_rot, target_quat) # define target in body coordinates
        else:
            print("UNKNOWN POINTING REFERENCE")
    
    def RW_LQR_controller(self, q_error, omega):
        x = np.concatenate((q_error[:3], omega)) # assemble state vector
        return -self.K_RW @ x # invert sign for control
    
    def mag_LQR_controller(self, q_error, omega):
        x = np.concatenate((q_error[:3], omega)) # assemble state vector
        return -self.K_MAG @ x # invert sign for control
      
    def b_mat(self, B):
        bx, by, bz = B
        return np.array([
            [0,   bz,  -by],
            [-bz,   0,  bx],
            [by, -bx,   0]
        ])