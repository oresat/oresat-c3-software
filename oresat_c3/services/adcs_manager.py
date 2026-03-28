"""'
ADCS controller service
"""
from datetime import datetime, timezone
from typing import Optional, Tuple, Any, TypedDict, Union

from canopen.objectdictionary import ODRecord
from olaf import Service, logger

import numpy as np
from time import time
from ..subsystems.adcs import quaternion as quat
from skyfield.api import load
from skyfield.framelib import itrs

from ..subsystems.adcs.config import ADCSConfig
# Custom GNC/ADCS functions
from ..subsystems.adcs.discrete_state_space import get_gain_matrix
from ..subsystems.adcs.kalman_filter import Multiplicative_Extended_Kalman_Filter
from ..subsystems.adcs import guidance_functions as guid

class TimestampedData(TypedDict):
    timestamp: int
    data: Any


class ADCSManager(Service):

    def __init__(self, config: ADCSConfig, mock_hw: bool = False):
        super().__init__()

        self.control_mode = config["control_mode"] # select control mode. Modes are "POINTING", "TRACKING", "DETUMBLE", "THERMAL_DETUMBLE", "THERMAL_REORIENT", and "THERMAL_SPINUP"
        self.guidance_mode = config["guidance_mode"] # select guidance mode. Modes are "TARGET", "NADIR", "MAX_DRAG", "MIN_DRAG"
        self.pointing_reference = config["pointing_reference"] # select reference payload (i.e. Selfie Cam or Cirrus Flux Camera). Modes are "SC" and "CFC". SENTINEL will only ever use "SC" for the high-gain antenna
        self.ECEF_target = guid.GPS_to_ECEF(config["target_lat"], config["target_lon"], config["target_height"], ) # used for tracking mode to set static ground target with GPS coordinates in ECEF
        self.updateTime = config["update_time"] # controller interval (seconds)
        self.rw_inertia = config["rw_inertia"] # # reaction wheel inertia (scalar)
        self.sat_inertia = config["sat_inertia"] # satellite inertia tensor (matrix)

        self.G = config["g"] # wheel orientation matrix
        self.G_transpose = self.G.T # save repeated calculations each iteration
        self.G_pinv = -np.linalg.pinv(self.G) # pseudo inverse matrix for torque calculations. NEGATE OR NOT????
        self.q_90_rot = quat.axis_angle_to_quaternion([0,1,0], -90) # translate star tracker targets to +z side of satellite by rotating by 90 degrees CW about the y axis
        self.q_180_rot = quat.axis_angle_to_quaternion([1,0,0], -180) # translate CFC targets to +z side/viewpoint of satellite. Chose rotation about x axis for this one so that satellite +x facing doesn't change in guidance functions

        self.q_target = np.array([0,0,0,1]) # attribute initialization, set by guidance functions
        self.spin_omega_target = np.array([0, 0, 0.034])
        self.filter_initialized = False

        # Controller gains
        
        self.use_variable_gain = config["use_variable_gain"]
        max_input = 0.001 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error = 1
        LQR_max_rate = 0.2
        self.K_RW = get_gain_matrix(self.sat_inertia, self.updateTime, LQR_max_error, LQR_max_rate, max_input)
        if self.use_variable_gain:
            self.gain_mode = 0 # start with "low" gain
            max_input = 0.01 # QUALITATIVE value for max torque used by LQR tuning ONLY
            LQR_max_error = .05
            LQR_max_rate = 0.2
            self.K_RW_fine = get_gain_matrix(self.sat_inertia, self.updateTime, LQR_max_error, LQR_max_rate, max_input) # define a fine pointing controller with aggressive error gains
        
        max_input_mag = 3 # QUALITATIVE value for max torque used by LQR tuning ONLY
        LQR_max_error_mag = 0.5
        LQR_max_rate_mag = 0.0003
        self.K_MAG = get_gain_matrix(self.sat_inertia, self.updateTime, LQR_max_error_mag, LQR_max_rate_mag, max_input_mag)

        # Controller gains
        Jmin = np.max(np.linalg.eigvals(self.sat_inertia)) # maximum principal moment of inertia (Markley & Crassidis defines this with the minimum principal moment of inertia as a safe upper bound to avoid instability, but maximum works better)
        self.detumble_gain = 4*np.pi/config["orbital_period"]*(1+np.sin(config["orbital_inclination"]*2*np.pi/180))*Jmin # gain based on minimal principal moment of inertia as defined in Markley & Crassidis

        # Kalman Filter
        self.EKF = Multiplicative_Extended_Kalman_Filter(
            config["star_tracker_uncertainty"],
            config["star_tracker_noise"],
            config["gyro_uncertainty"],
            config["gyro_noise"],
            config["gyro_bias_drift"]
        )

        self.skyfield_timescale = load.timescale()
        self.skyfield_EOP = itrs # Earth Orientation Parameters  UPDATE THIS TO POINT TO ACTUAL FILE || IMPORTANT TO UPDATE, SENSITIVE TO ERRORS OVER TIME

        # self.maxTorque = 0.01 # maximum torque output of reaction wheel [Nm]
        self.maxTorque = 0.001 # maximum torque output of reaction wheel [Nm]
        self.thermal_spin_rpm = 1.0 # thermal spin rate about the z-axis (body frame)
        self.omega_desired_prev = np.zeros(3) # for feed forward term

        self._tpdo_mapped_callbacks = {
            "star_tracker_1": {
                "cb": self._on_star_tracker_data,
                "idx": (
                    "orientation_time_since_midnight", "orientation_attitude_known",
                    "orientation_attitude_i", "orientation_attitude_j", "orientation_attitude_k",
                    "orientation_attitude_real"
                )
            },
            "gps": {
                "cb": self._on_gps_data,
                "idx": (
                    "skytraq_ecef_x", "skytraq_ecef_y", "skytraq_ecef_z",
                    "skytraq_ecef_vx", "skytraq_ecef_vy", "skytraq_ecef_vz"
                )
            },
            "adcs": {
                "cb": self._on_imu_data,
                "idx": (
                    "gyroscope_pitch_rate", "gyroscope_yaw_rate", "gyroscope_roll_rate"
                )
            }
        }
        self.last_sensor_time: dict[str, int] = { "star_tracker": -1, "imu": -1, "gps": -1 }
        self._sensor_data: dict[str, TimestampedData] = {
            "star_tracker": {
                "timestamp": -1,
                "data": {
                    "attitude_known": False,
                    "orientation": []
                }
            },
            "imu": {
                "timestamp": -1,
                "data": [] # pitch, roll, yaw
            },
            "gps": {
                "timestamp": -1,
                "data": {
                    "position": [],
                    "velocity": []
                }
            }
        }
        self._sensor_data_buffer: dict[str, TimestampedData] = {}
        self._sensor_data_valid_buffer: dict[str, dict[str, bool]] = {}

    def on_start(self):
        # add SDO callbacks, which are also called for relevant PDOs
        # at the same time, initialize valid data tracking
        for k, v in self._tpdo_mapped_callbacks.items():
            self._sensor_data_valid_buffer[k] = {}
            for subindex in v["idx"]:
                self._sensor_data_valid_buffer[k][subindex] = False
                self.node.add_sdo_callbacks(
                    k, subindex, None,
                    lambda value, f=v["cb"], idx=subindex: f(idx, value)
                )

    @property
    def is_data_available(self) -> bool:
        for v in self._sensor_data.values():
            if v["timestamp"] < 0:
                return False
        return True

    def initialize_filter(self): # initializes/resets extended kalman filter
        omega = self._sensor_data["imu"]["data"]
        q = self._sensor_data["star_tracker"]["data"]["orientation"]
        init_time = time()
        self.EKF.reset(q, omega, init_time) # reset filter states for next maneuver CHECK IF STAR TRACKER WAS AVAILABLE

    def update_ECEF_target(self, target_lat, target_lon, target_height):
        self.ECEF_target = guid.GPS_to_ECEF(target_lat, target_lon, target_height) # convert GPS coordinates to ECEF coordinates

    def on_loop(self):
        '''
        primary control loop
        '''

        '''
        Dynamic guidance functions for target tracking, nadir-pointing, and
        minimum & maximum drag orientation. This is separate from the control
        portion of the code, and just defines the target which is fed into the 
        control algorithms
        '''
        
        if (self.control_mode in ("RW_POINTING", "THERMAL_REORIENT")) and not self.filter_initialized:
            omega = self._sensor_data["imu"]["data"]
            if not self.is_data_available:
                return
            if not self._sensor_data["star_tracker"]["data"]["attitude_known"]:
                d_omega = self.spin_omega_target-omega # desired delta omega
                tau = self.satInertia @ d_omega/self.updateTime/5 # divide by five to smooth control inputs
                wheel_torque = self.G_pinv @ tau
                # COMMAND WHEEL TORQUES HERE
            else:
                self.initialize_filter()
                
        if self.guidance_mode in (
            "TRACKING", # track static target on Earth's surface
            "NADIR",
            "MAX_DRAG", # Orient satellite with largest face ram-pointing (+x)
            "MIN_DRAG", # Orient satellite with smallest face ram-pointing (+z)
        ):

            r_ECEF, v_ECEF = self._sensor_data["gps"]["data"].values()
            dt: datetime = datetime.now(timezone.utc) # get current ephemeris time from last GPS update
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
                new_target = None
                print(f"Unknown guidance mode: {self.guidance_mode}")

            q_last = self.q_target # save for tracking rate calculations
            self.update_target(new_target) # update FSW target

        if self.control_mode in ("RW_POINTING", "THERMAL_REORIENT"):
            # get sensor data and modify for consumption by control algorithms
            wheel_speeds = np.array([
                self.node.od["rw_1"]["motor_velocity"].value,
                self.node.od["rw_2"]["motor_velocity"].value,
                self.node.od["rw_3"]["motor_velocity"].value,
                self.node.od["rw_4"]["motor_velocity"].value,
            ]) * 2 * np.pi
            star_tracker_output: Optional[TimestampedData] = self.get_sensor_data(["star_tracker"])[0]
            omega = np.array(self.get_sensor_data(["imu"])[0]["data"])
            if star_tracker_output and star_tracker_output["data"]["attitude_known"]: # if attitude_known flag is 1 (true), data is valid
                q_star_tracker = star_tracker_output["data"]["orientation"]
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker) # rotate star tracker output into body frame
            else:
                q_st_rotated = None

            q, omega = self.EKF.update(datetime.now(timezone.utc).timestamp(), omega, q_st_rotated) # update filter with applicable data

            q_last = self.q_target # save last target for feed-forward terms
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
            h_wheels = self.rw_inertia * wheel_speeds @ self.G.T # calculate stored wheel momentum in body frame (resulting in a 3x1 vector of angular momentum axis elements in body frame)
            tau_ff = self.sat_inertia @ alpha_d_B + np.cross(omega, self.sat_inertia @ omega + h_wheels) # total feed-forward torque accounting for gyroscopic coupling

            omega = omega-omega_desired # set biased omega after using true value to calculate feed forward term

            '''
            Send torque commands reaction wheels
            '''

            desired_torque = self.RW_controller(q_error, omega, time()) # compute desired 3-axis torque from controller. Pass in time for variable gain controller
            desired_torque = desired_torque+tau_ff # add feedforward terms
            wheel_torque = self.G_pinv @ desired_torque # convert desired 3-axis torque to inputs for 4 reaction wheels
            # COMMAND REACTION WHEELS HERE

            if (self.control_mode == "THERMAL_REORIENT") and (quat.error_angle(q_error) <= 0.1) and (np.all(np.abs(omega) < 1e-6)):
                # ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS! Must wait for wheels to turn off, but they should be at zero already by the end of the maneuver. If not, there is a problem.
                self.control_mode = "THERMAL_SPINUP" # change mission mode to spin-up with magnetorquers

            '''
            The following sections contain all magnetorquer control algorithms
            '''

        elif (self.control_mode == "DETUMBLE") or (self.control_mode == "THERMAL_DETUMBLE"): # enter 3-step passive thermal-spin mode by first detumbling with magnetorquers
            omega = self._sensor_data["imu"]["data"]
            B = self.get_magnetometer_data()
            desired_torque = self.detumble_gain/(np.linalg.norm(B)**2)*np.cross(omega, B) # detumble controller as defined by Markley & Crassidis
            # COMMAND MAGNETORQUERS

            if (self.control_mode == "THERMAL_DETUMBLE") and (np.all(np.abs(omega) < 1e-4)): # if using 3-step passive thermal-spin controller, check for
                self.control_mode = "THERMAL_REORIENT"
                self.initialize_filter() # reset filter as it hasn't been used since reaction wheels last

        elif self.control_mode == "THERMAL_SPINUP": # spin up about satellite's z-axis using magnetorquer
            omega = self._sensor_data["imu"]["data"]
            B = self.get_magnetometer_data()
            if omega[2] < self.thermal_spin_rpm*2*np.pi/60: # while satellite is spinning slower than set rate about the z axis, spin up
                tau_des = [0,0,1] # spin about the z axis
                desired_torque = np.cross(B, tau_des) / (B @ B)
                # COMMAND MAGNETORQUERS

        elif self.control_mode == "MTB_POINTING":
            omega = self._sensor_data["imu"]["data"]
            B = self.get_magnetometer_data()
            star_tracker_output: Optional[TimestampedData] = self.get_sensor_data(["star_tracker"])[0]
            if star_tracker_output and star_tracker_output["data"]["attitude_known"]:
                q_star_tracker = star_tracker_output["data"]["orientation"] # unpack scalar last quaternion array from message
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker) # rotate star tracker output into body frame
            else:
                q_st_rotated = None

            q, omega = self.EKF.update(datetime.now(timezone.utc).timestamp(), omega, q_st_rotated) # update filter with applicable data
            q_error = quat.quat_error(self.q_target, q) # get error quaternion, this function automatically sanitizes by performing normalization and hemisphere checks
            q_error = quat.hemi(q_error) # only apply hemisphere check once, after determining error quaternion to maintain associativity across hermisphere boundaries
            
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

    def RW_controller(self, q_error, omega, currentTimeSecs):
        x = np.concatenate((q_error[:3], omega)) # assemble state vector            

        if self.use_variable_gain and (quat.error_angle(q_error) < 1): # LQR controller with integral term
            transient_time = 30 # seconds
            if self.gain_mode == 0:
                self.transient_start = currentTimeSecs
                self.gain_mode = 1 # switch to transient mode
                return - self.K_RW @ x # firt step of transient mode returns the same as standard controller
            elif self.gain_mode == 1:
                if (self.transient_start >= self.transient_start+transient_time):
                    self.gain_mode = 2 # switch to full fine-pointing mode
                gain_switch_time = currentTimeSecs - self.transient_start
                return (-self.K_RW_fine @ x)*gain_switch_time/transient_time - (self.K_RW @ x)*(1-gain_switch_time/transient_time) # transient mode
            else:
                return -self.K_RW_fine @ x # - self.K_integrator @ self.state_integral
        else:
            self.gain_mode = 0 # standard gains
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

    def _data_buffer_valid(self, index: str) -> bool:
        # FIXME: ensure works for dict data and list data
        v = self._sensor_data_buffer.values()
        if v and v["timestamp"] >= 0:
            for data in v:
                if not data:
                    return False
        else:
            return False

        return True

    def _on_star_tracker_data(self, subindex: str, value: Union[bool, float]):
        # TODO: move duplicate logic to decorator
        logger.debug("ADCS received star tracker data: {}={}", subindex, value)
        buf: Optional[TimestampedData] = self._sensor_data_buffer.get("star_tracker", None)
        if not buf:
            buf = TimestampedData(timestamp=-1, data={ "attitude_known": None, "orientation": np.zeros(4) })
            self._sensor_data_buffer["star_tracker"] = buf
            # reset validity buf
            k: str
            for k in self._sensor_data_valid_buffer["star_tracker"]:
                self._sensor_data_valid_buffer["star_tracker"][k] = False
            
        if subindex == "orientation_time_since_midnight":
            buf["timestamp"] = value
            self._sensor_data_valid_buffer["star_tracker"][subindex] = True
        elif subindex == "orientation_attitude_known":
            buf["data"]["attitude_known"] = value
        elif subindex == "orientation_attitude_i":
            buf["data"]["orientation"][0] = value
        elif subindex == "orientation_attitude_j":
            buf["data"]["orientation"][1] = value
        elif subindex == "orientation_attitude_k":
            buf["data"]["orientation"][2] = value
        elif subindex == "orientation_attitude_real":
            buf["data"]["orientation"][3] = value
        else:
            logger.error("ADCS received invalid star tracker PDO data subindex")
            return

        self._sensor_data_valid_buffer["star_tracker"][subindex] = True

        if _data_buffer_valid("star_tracker"):
            self._sensor_data["star_tracker"] = self._sensor_data_buffer.pop("star_tracker")

    def _on_gps_data(self, subindex: str, value: float) -> Optional[Tuple[list, list]]:
        logger.debug(f"ADCS received GPS data {subindex}={value}")
        if subindex == "skytraq_time_since_midnight":
            # set or create new entry
            self._sensor_data_buffer["gps"] = TimestampedData(timestamp=value, data={
                "position": [0,0,0],
                "velocity": [0,0,0],
            })
        elif subindex == "skytraq_ecef_x":
            self._sensor_data_buffer["gps"]["data"]["position"][0] = value
        elif subindex == "skytraq_ecef_y":
            self._sensor_data_buffer["gps"]["data"]["position"][1] = value
        elif subindex == "skytraq_ecef_z":
            self._sensor_data_buffer["gps"]["data"]["position"][2] = value
        elif subindex == "skytraq_ecef_vx":
            self._sensor_data_buffer["gps"]["data"]["velocity"][0] = value
        elif subindex == "skytraq_ecef_vy":
            self._sensor_data_buffer["gps"]["data"]["velocity"][1] = value
        elif subindex == "skytraq_ecef_vz":
            self._sensor_data_buffer["gps"]["data"]["velocity"][2] = value
            # expect vz is last to arrive
            self._sensor_data["gps"] = self._sensor_data_buffer["gps"]

    def _on_imu_data(self, subindex: str, value: Any) -> Optional[list]:
        logger.debug(f"ADCS received IMU data {subindex}={value}")
        # FIXME: the timestamp should be sent from the IMU
        if subindex == "gyroscope_pitch_rate":
            dt = datetime.today()
            ms_since_midnight = (((((dt.hour * 60) + dt.minute) * 60) + dt.second) * 1000) + (dt.microsecond // 1000)
            self._sensor_data_buffer["imu"] = TimestampedData(timestamp=ms_since_midnight, data=[value, 0, 0])
        elif subindex == "gyroscope_yaw_rate":
            self._sensor_data_buffer["imu"]["data"][1] = value
        elif subindex == "gyroscope_roll_rate":
            self._sensor_data_buffer["imu"]["data"][2] = value
            self._sensor_data["imu"] = self._sensor_data_buffer["imu"]

    def get_magnetometer_data(self) -> Any: # FIXME: type for NDArray of float32 when numpy.typing is available
        # TODO: check format of data: OD shows int16, unit: Gauss

        # there are FOUR magnetometers (2 on +Z end card, 2 on -Z)
        # for now the solution is to average their readings
        field_vectors: list = []
        adcs_record: ODRecord = self.node.od["adcs"]
        for direction in ("pos", "min"):
            for num in range(2):
                vec: list[float] = []
                for dim in ("x", "y", "z"):
                    vec.append(
                        adcs_record[
                            f"{direction}_z_magnetometer_{num}_{dim}"
                        ].value
                    )
                field_vectors.append(np.array(vec))

        return sum(np.array(field_vectors)) / len(field_vectors)

    def get_sensor_data(self, sensor_list) -> list[Optional[TimestampedData]]:
        """Get data from list of sensor names

        Parameters
        ----------
        sensor_list : list
            a list of sensor names

        Returns
        -------
        list[Optional[TimestampedData]]
            A list of sensor data, in the same order as sensor_list, or
            None if no new data is available.
        """

        return_list = []
        for sensor in sensor_list:
            data = self._sensor_data[sensor]
            if data["timestamp"] == self.last_sensor_time[sensor]:
                return_list.append(None)
            else:
                self.last_sensor_time[sensor] = data["timestamp"]
                return_list.append(self._sensor_data[sensor])

        return return_list
