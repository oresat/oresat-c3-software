"""'
ADCS controller service
"""
from typing import Optional, Tuple, Callable

from olaf import Service

import numpy as np
from ..subsystems.adcs import quaternion as quat
from skyfield.api import load
from skyfield.framelib import itrs

# Custom GNC/ADCS functions
from ..subsystems.adcs.discrete_state_space import get_gain_matrix
from ..subsystems.adcs.kalman_filter import Multiplicative_Extended_Kalman_Filter
from ..subsystems.adcs import guidance_functions as guid


class ADCSManager(Service):
    def __init__(self, mock_hw: bool = False):
        super().__init__()
        
        config = None # TEMPORARY PLACE HOLDER TO GET RID OF LINTING ERRORS
        
        self.control_mode = None # select control mode. Modes are "POINTING", "TRACKING", "DETUMBLE", "THERMAL_DETUMBLE", "THERMAL_REORIENT", and "THERMAL_SPINUP"
        self.guidance_mode = None # select guidance mode. Modes are "TARGET", "NADIR", "MAX_DRAG", "MIN_DRAG"
        self.pointing_reference = None # select reference payload (i.e. Selfie Cam or Cirrus Flux Camera). Modes are "SC" and "CFC" 
        self.q_target = None # target quaternion for controller error calculations
        self.ECEF_target = None # used for tracking mode to set static ground target with GPS coordinates in ECEF
        self.updateTime = None # controller interval (seconds)
        self.rwInertia = None # # reaction wheel inertia (scalar)
        self.satInertia = None # satellite inertia tensor (matrix)
        
        self.G = config["G"] # wheel orientation matrix
        self.G_transpose = self.G.T # save repeated calculations each iteration
        self.G_pinv = -np.linalg.pinv(self.G) # pseudo inverse matrix for torque calculations. NEGATE OR NOT????
        self.q_90_rot = quat.axis_angle_to_quaternion([0,1,0], -90) # translate star tracker targets to +z side of satellite by rotating by 90 degrees CW about the y axis
        self.q_180_rot = quat.axis_angle_to_quaternion([1,0,0], -180) # translate CFC targets to +z side/viewpoint of satellite. Chose rotation about x axis for this one so that satellite +x facing doesn't change in guidance functions
        
        self.q_target = np.array([0,0,0,1]) # attribute initialization, set to real value in sim main
        omega_target_rpm = np.array([0.0, 0.0, 0.0]) # [RPM]
        self.omega_target = omega_target_rpm * 2*np.pi/60 # convert to [rad/s]
        
        # Controller gains        
        max_input = 0.001 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error = 1
        LQR_max_rate = 0.2
        self.K_RW = get_gain_matrix(self.satInertia, self.updateTime, LQR_max_error, LQR_max_rate, max_input) # calculate reaction wheel LQR gain matrix
        
        max_input_mag = 3 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error_mag = 0.5
        LQR_max_rate_mag = 0.0003
        self.K_MAG = get_gain_matrix(self.satInertia, self.updateTime, LQR_max_error_mag, LQR_max_rate_mag, max_input_mag)
        
        # Controller gains
        Jmin = np.max(np.linalg.eigvals(self.satInertia)) # maximum principal moment of inertia (Markley & Crassidis defines this with the minimum principal moment of inertia as a safe upper bound to avoid instability, but maximum works better)
        self.detumble_gain = 4*np.pi/config["orbital_period"]*(1+np.sin(config["orbital_inclination"]*2*np.pi/180))*Jmin # gain based on minimal principal moment of inertia as defined in Markley & Crassidis
        
        # Kalman Filter
        self.EKF = Multiplicative_Extended_Kalman_Filter(config["P_ST_0"], config["sigma_ST"], config["P_b0"], config["sigma_gyro"], config["sigma_bias"])

        self.skyfield_timescale = load.timescale()
        self.skyfield_EOP = itrs # Earth Orientation Parameters  UPDATE THIS TO POINT TO ACTUAL FILE || IMPORTANT TO UPDATE, SENSITIVE TO ERRORS OVER TIME
        
        # self.maxTorque = 0.01 # maximum torque output of reaction wheel [Nm]
        self.maxTorque = 0.001 # maximum torque output of reaction wheel [Nm]
        self.thermal_spin_rpm = 1.0 # thermal spin rate about the z-axis (body frame)
        self.omega_desired_prev = np.zeros(3) # for feed forward term

        # star_tracker_1, adcs [gyroscope, accelerometer, magnetometer], gps
        self.last_sensor_time: dict[str, int] = {"star_tracker":0, "imu":0, "magnetometer":0, "gps":0} # save last update time for all sensors
        self.__sensor_data_map: dict[str, Callable] = {"star_tracker": self.get_star_tracker_data, "imu": self.get_imu_data, "magnetometer": self.get_mag_data, "gps": self.get_gps_data}
        
    def on_start(self):
        # initialize filter with star tracker and gyro data if using one of the reaction wheel mode
        if self.control_mode in ("RW_POINTING", "THERMAL_REORIENT"):
            self.initialize_filter()
    
    def initialize_filter(self): # initializes/resets extended kalman filter
        omega = self.node.od['adcs']['IMU']
        q = self.node.od['adcs']['star_tracker']
        init_time = self.node.od['adcs']['IMU_time']
        self.EKF.reset(q, omega, init_time) # reset filter states for next maneuver CHECK IF STAR TRACKER WAS AVAILABLE
    
    def update_ECEF_target(self, target_lat, target_lon, target_height):
        self.ECEF_target = guid.GPS_to_ECEF(target_lat, target_lon, target_height) # convert GPS coordinates to ECEF coordinates
        
    def on_loop(self, currentTimeNanos):
        '''
        primary control loop
        '''
        
        '''
        Dynamic guidance functions for target tracking, nadir-pointing, and
        minimum & maximum drag orientation. This is separate from the control
        portion of the code, and just defines the target which is fed into the 
        control algorithms
        '''
        
        if self.guidance_mode in (
            "TRACKING",
            "NADIR",
            "MAX_DRAG",
            "MIN_DRAG",
        ):
            
            r_ECEF, v_ECEF = self.get_sensor_data(['GPS']) # get ECEF position and velocity vectors
            # FIXME: time is milliseconds since midnight (gps epoch) -> convert to datetime
            dt = self.last_sensor_time['GPS_time'] # get current ephemeris time from last GPS update
            t = self.skyfield_timescale.from_datetime(dt) # set ephemeris calculation time
            ECI_2_ECEF = self.skyfield_EOP.rotation_at(t) # inertial -> ECEF rotation matrix
            nadir_vector_ECEF = -r_ECEF / np.linalg.norm(r_ECEF) # used to get correct facing for star tracker. Nadir vector is opposite of vector from earth.

            if self.guidance_mode == "TARGET": # Tracking a static target on the surface of the earth via GPS coordinates        
                target_vector = self.ECEF_target - r_ECEF # calculate target vector in ECEF cartesian coordinates
                target_vector = target_vector/np.linalg.norm(target_vector) # normalize to unit vector
                new_target = guid.target_tracking_quat(target_vector, nadir_vector_ECEF, ECI_2_ECEF) # create orientation quaternion from cartesian target
            elif self.guidance_mode == "NADIR": # Continually face +z nadir (+x as close to ram as possible)
                new_target = guid.nadir_quat(nadir_vector_ECEF, v_ECEF, ECI_2_ECEF) # create orientation quaternion from cartesian target
            elif self.guidance_mode == "MAX_DRAG" or self.guidance_mode == "MIN_DRAG":
                new_target = guid.ram_quaternion(self.guidance_mode, v_ECEF, nadir_vector_ECEF, ECI_2_ECEF) # calculate ram-facing orientation for either +z or +x axis based on min or max drag
            else:
                print(f"Unknown guidance mode: {self.guidance_mode}")
            
            q_last = self.q_target # save for tracking rate calculations
            self.update_target(new_target) # update FSW target
            
        if self.control_mode in ("RW_POINTING", "THERMAL_REORIENT"):
            # get sensor data and modify for consumption by control algorithms
            wheelSpeeds = self.node.od['adcs']['RW_speeds'] # get reaction wheel speeds
            star_tracker_output, omega = self.get_sensor_data(['star_tracker', 'IMU']) # get sensor data for star tracker and IMU
            if star_tracker_output[0] == 1: # if attitude_known flag is 1 (true), data is valid
                q_star_tracker = star_tracker_output[1] # unpack scalar last quaternion array from message
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker) # rotate star tracker output into body frame
            else:
                q_st_rotated = None
            
            q, omega = self.EKF.update(currentTimeNanos*1e-9, omega, q_st_rotated) # update filter with applicable data
            
            q_last = self.q_target # save last target for feed-forward terms
            self.update_tracking_quat() # update target orientation based on current orientation and fixed target

            q_error = quat.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = quat.hemi(q_error) # only apply hemisphere check once, after determining error quaternion to maintain associativity across hermisphere boundaries
            
            '''
            The following section includes feed-forward terms for target tracking
            to avoid overdamping and to account for gyroscopic effects 
            '''
            
            # feed forward term for angular rate bias
            rotation_quat = quat.quat_error(q_last, self.q_target) # flipped order because of frame conventions for proper signage (body -> target)
            rot_axis = quat.quat_to_axis(rotation_quat)
            rot_angle = quat.error_angle(rotation_quat) * np.pi/180
            omega_desired = rot_axis*(rot_angle/self.updateTime) # set rotation rate for tracking maneuver
            
            # feed forward term to account for stored angular momentum
            alpha_d_B = (omega_desired - self.omega_desired_prev) / self.updateTime # desired acceleration in body frame
            self.omega_desired_prev = omega_desired.copy() # update previous target rate
            H_wheels = self.rwInertia * np.asarray(wheelSpeeds[:4]) @ self.G.T # calculate stored wheel momentum in body frame (resulting in a 3x1 vector of angular momentum axis elements in body frame)
            tau_ff = self.satInertia @ alpha_d_B + np.cross(omega, self.satInertia @ omega + H_wheels) # total feed-forward torque accounting for gyroscopic coupling
        
            omega = omega-omega_desired # set biased omega after using true value to calculate feed forward term
            
            '''
            Send torque commands reaction wheels
            '''
            
            desired_torque = quat.quaternion_controller(q_error, omega) # compute desired 3-axis torque from controller
            desired_torque = desired_torque+tau_ff # add feedforward terms
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            # COMMAND REACTION WHEELS HERE
            
            if (self.control_mode == "THERMAL_REORIENT") and (self.error_angle(q_error) <= 0.1) and (np.all(np.abs(omega) < 1e-6)):
                # ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS! Must wait for wheels to turn off, but they should be at zero already by the end of the maneuver. If not, there is a problem.
                self.control_mode = "THERMAL_SPINUP" # change mission mode to spin-up with magnetorquers
        
            '''
            The following sections contain all magnetorquer control algorithms
            '''
        
        elif ((self.control_mode == "DETUMBLE") or (self.control_mode == "THERMAL_DETUMBLE")): # enter 3-step passive thermal-spin mode by first detumbling with magnetorquers
            omega = self.node.od['adcs']['omega'] # get gyro data
            B = self.node.od['adcs']['magnetometer'] # get magnetometer data
            desired_torque = self.detumble_gain/(np.linalg.norm(B)**2)*np.cross(omega, B) # detumble controller as defined by Markley & Crassidis
            # COMMAND MAGNETORQUERS 
            
            if ((self.control_mode == "THERMAL_DETUMBLE") and (np.all(np.abs(omega) < 1e-4))): # if using 3-step passive thermal-spin controller, check for 
                self.control_mode = "THERMAL_REORIENT"
                self.initialize_filter() # reset filter as it hasn't been used since reaction wheels last 
        
        elif self.control_mode == "THERMAL_SPINUP": # spin up about satellite's z-axis using magnetorquer
            omega = self.node.od['adcs']['omega'] # get gyro data
            B = self.node.od['adcs']['magnetometer'] # get magnetometer data
            if (omega[2] < self.thermal_spin_rpm*2*np.pi/60): # while satellite is spinning slower than set rate about the z axis, spin up
                tau_des = [0,0,1] # spin about the z axis
                desired_torque = np.cross(B, tau_des) / (B @ B)
                # COMMAND MAGNETORQUERS
        
        elif self.control_mode == "MTB_POINTING":
            tau_des = self.mag_LQR_controller(q_error, omega) # desired 3-axis torque in body frame
            bm = self.b_mat(B)
            k = 1e-8
            m_cmd = np.linalg.inv(bm.T @ bm + k*np.eye(3))@bm.T@tau_des
            # COMMAND MAGNETORQUERS 

            # Should we add exit clause? How would we shut down adcs with a flag???
        
        else:
            print("Unknown control mode!")
    
    def update_target(self, target_quat): # UPDATE THIS FUNCTION TO USE POINTING REFERENCE AS AN ARGUMENT???
        if self.pointing_reference == "ST":
            self.q_target = quat.quat_mult(self.q_90_rot, target_quat) # define target in body coordinates
        elif self.pointing_reference == "SC":
            self.q_target = target_quat # target does not require rotation
        elif self.pointing_reference == "CFC":
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

    def get_star_tracker_data(self):
        time_since: int = self.node.od["star_tracker_1"]["orientation_time_since_midnight"].value
        if self.last_sensor_time["star_tracker"] == time_since:
            return None
        a: int = self.node.od["star_tracker_1"]["orientation_right_ascension"].value
        b: int = self.node.od["star_tracker_1"]["orientation_declination"].value
        c: int = self.node.od["star_tracker_1"]["orientation_roll"].value
        # TODO: convert to scalar-last quaternion
        return [a, b, c]

    def get_gps_data(self) -> Optional[Tuple[list, list]]:
        time_since = self.node.od["gps"]["skytraq_time_since_midnight"].value
        if self.last_sensor_time["gps"] == time_since:
            return None
        self.last_sensor_time["gps"] = time_since
        ecef_x = self.node.od["gps"]["skytraq_ecef_x"].value
        ecef_y = self.node.od["gps"]["skytraq_ecef_y"].value
        ecef_z = self.node.od["gps"]["skytraq_ecef_z"].value
        ecef_vx = self.node.od["gps"]["skytraq_ecef_vx"].value
        ecef_vy = self.node.od["gps"]["skytraq_ecef_vy"].value
        ecef_vz = self.node.od["gps"]["skytraq_ecef_vz"].value
        return [ecef_x, ecef_y, ecef_z], [ecef_vx, ecef_vy, ecef_vz]

    def get_imu_data(self) -> Optional[list]:
        # TODO: time checking
        pitch_rate: int = self.node.od["adcs"]["gyroscope_pitch_rate"].value
        yaw_rate: int = self.node.od["adcs"]["gyroscope_yaw_rate"].value
        roll_rate: int = self.node.od["adcs"]["gyroscope_roll_rate"].value
        return [pitch_rate, yaw_rate, roll_rate]

    def get_mag_data(self) -> Optional[np.typing.NDArray[np.float32]]:
        # TODO: time checking
        # TODO: check format of data: OD shows int16, unit: Gauss

        # there are FOUR magnetometers (2 on +Z end card, 2 on -Z)
        # for now the solution is to average their readings
        field_vectors: list = []
        for direction in ("pos", "min"):
            for num in range(2):
                vec = []
                for dim in ("x", "y", "z"):
                    vec.append(
                        self.node.od["adcs"][
                            f"{direction}_z_magnetometer_{num}_{dim}"
                        ].value
                    )
                field_vectors.append(np.array(vec))

        return sum(np.array(field_vectors)) / len(field_vectors)

    def get_sensor_data(self, sensor_list):
        '''
        Dynamic function to get data from list of sensor names, and store last
        sensor update time for Kalman filter usage
        '''
        
        return_list = []
        for sensor in sensor_list:
            sensor_time = self.node.od[sensor + '_time']
            if sensor_time > self.last_sensor_time[sensor]: # if data is newer than last update, append to return list
                return_list.append(self.node.od['adcs'][sensor]) # append sensor data to return list
                self.last_sensor_time[sensor] = sensor_time # update last sensor time
            else:
                return_list.append(None) # else list sensor as None to indicate no new data
        
        return return_list # reutrn list of sensor data (or None if sensor hasn't updated this loop)