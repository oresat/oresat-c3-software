"""
ADCS Manager Service

Handles collecting sensor data from the Star Tracker, IMU, magnetometers, and GPS. Using this data,
it can calculate attitude adjustments and execute those adjustments by commanding reaction wheels
and magnetorquers.
"""

import functools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import time, sleep
from typing import Callable, Optional, Tuple, Type, TypeVar, Union

import numpy as np
from canopen.objectdictionary import ODRecord
from olaf import Service, logger
from skyfield.api import load
from skyfield.framelib import itrs
from typing_extensions import Concatenate, ParamSpec

from ..subsystems.adcs import guidance_functions as guid
from ..subsystems.adcs import quaternion as quat
from ..subsystems.adcs.config import ADCSConfig
from ..subsystems.adcs.discrete_state_space import get_gain_matrix
from ..subsystems.adcs.kalman_filter import MEKF


@dataclass
class StarTrackerData:
    attitude_known: bool = False
    orientation: np.ndarray = field(default_factory=lambda: np.zeros(4))


@dataclass
class GPSData:
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    velocity: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])


@dataclass
class IMUData:
    gyro: np.ndarray = field(default_factory=lambda: np.zeros(3))


@dataclass
class TimestampedData:
    timestamp: int
    data: Union[StarTrackerData, GPSData, IMUData]


@dataclass
class CallbackDataMapping:
    callback: Callable[[str, Union[bool, float], TimestampedData], None]
    dataclass: Type[Union[StarTrackerData, GPSData, IMUData]]
    od_indices: Tuple[str]


P = ParamSpec("P")
R = TypeVar("R")
S = TypeVar("S")


def adcs_callback(
    key: str,
) -> Callable[[Callable[Concatenate[S, P], R]], Callable[Concatenate[S, P], R]]:
    def decorator(func: Callable[Concatenate[S, P], R]) -> Callable[Concatenate[S, P], R]:
        @functools.wraps(func)
        def wrapper(self: S, *args: P.args, **kwargs: P.kwargs) -> R:
            logger.debug("ADCS received {} data: {}={}", key, *args)
            buf: Optional[TimestampedData] = self._sensor_data_buffer.get(key, None)
            if not buf:
                buf = TimestampedData(-1, self._data_mapping[key].dataclass())
                self._sensor_data_buffer[key] = buf
                # reset validity buf
                k: str
                for k in self._sensor_data_valid_buffer[key]:
                    self._sensor_data_valid_buffer[key][k] = False
            func(self, *args, **kwargs, buf=buf)
            self._sensor_data_valid_buffer[key][args[0]] = True
            if self._data_buffer_valid(key):
                logger.debug("Data buffer filled for {}", key)
                self._sensor_data[key] = self._sensor_data_buffer.pop(key)

        return wrapper

    return decorator


class ADCSManager(Service):

    def __init__(self, config: ADCSConfig, mock_hw: bool = False) -> None:
        super().__init__()
        self.control_mode: str = config["control_mode"]
        self.guidance_mode: str = config["guidance_mode"]
        self.pointing_reference: str = config["pointing_reference"]
        # used for tracking mode to set static ground target with GPS coordinates in ECEF
        self.ECEF_target: np.ndarray = guid.gps_to_ecef(
            config["target_lat"], config["target_lon"], config["target_height"]
        )
        self.update_time: float = config["update_time"]
        self.rw_inertia: float = config["rw_inertia"]
        self.sat_inertia: np.ndarray = config["sat_inertia"]

        self.G: np.ndarray = config["g"]
        self.G_transpose: np.ndarray = self.G.T  # save repeated calculations each iteration
        self.G_pinv: np.ndarray = -np.linalg.pinv(self.G)
        # translate star tracker targets to +z side of satellite
        # by rotating by 90 degrees CW about the y axis
        self.q_90_rot: np.ndarray = quat.axis_angle_to_quaternion([0, 1, 0], -90)

        # translate CFC targets to +z side/viewpoint of satellite
        # Chose rotation about x axis for this one
        # so that satellite +x facing doesn't change in guidance functions
        self.q_180_rot: np.ndarray = quat.axis_angle_to_quaternion([1, 0, 0], -180)

        self.q_target: np.ndarray = np.array([0, 0, 0, 1])
        self.spin_omega_target: np.ndarray = np.array([0, 0, 0.034])
        self.filter_initialized: bool = False

        # Controller gains
        self.use_variable_gain: bool = config["use_variable_gain"]
        max_input: float = 0.001  # QUALITATIVE value for max torque used by LQR tuning ONLY
        lqr_max_error: float = 1
        lqr_max_rate: float = 0.2
        self.K_RW: np.ndarray = get_gain_matrix(
            self.sat_inertia, self.update_time, lqr_max_error, lqr_max_rate, max_input
        )
        if self.use_variable_gain:
            self.gain_mode: int = 0  # start with "low" gain
            max_input = 0.01  # QUALITATIVE value for max torque used by LQR tuning ONLY
            lqr_max_error = 0.05
            lqr_max_rate = 0.2
            self.K_RW_fine: np.ndarray = get_gain_matrix(
                self.sat_inertia, self.update_time, lqr_max_error, lqr_max_rate, max_input
            )  # define a fine pointing controller with aggressive error gains

        max_input_mag: float = 3  # QUALITATIVE value for max torque used by LQR tuning ONLY
        lqr_max_error_mag: float = 0.5
        lqr_max_rate_mag: float = 0.0003
        self.K_MAG: np.ndarray = get_gain_matrix(
            self.sat_inertia, self.update_time, lqr_max_error_mag, lqr_max_rate_mag, max_input_mag
        )

        """
        maximum principal moment of inertia
        (Markley & Crassidis defines this with the minimum principal moment of inertia as a safe
        upper bound to avoid instability, but maximum works better)
        """
        j_min: float = np.max(np.linalg.eigvals(self.sat_inertia))
        # gain based on minimal principal moment of inertia as defined in Markley & Crassidis
        self.detumble_gain: float = (
            4
            * np.pi
            / config["orbital_period"]
            * (1 + np.sin(config["orbital_inclination"] * 2 * np.pi / 180))
            * j_min
        )

        self.EKF: MEKF = MEKF(
            config["star_tracker_uncertainty"],
            config["star_tracker_noise"],
            config["gyro_uncertainty"],
            config["gyro_noise"],
            config["gyro_bias_drift"],
        )

        self.skyfield_timescale = load.timescale()
        # Earth Orientation Parameters
        # UPDATE THIS TO POINT TO ACTUAL FILE || IMPORTANT TO UPDATE, SENSITIVE TO ERRORS OVER TIME
        self.skyfield_EOP = itrs

        self.max_torque: float = 0.001  # maximum torque output of reaction wheel [Nm]
        self.thermal_spin_rpm: float = 1.0  # thermal spin rate about the z-axis (body frame)
        self.omega_desired_prev: np.ndarray = np.zeros(3)  # for feed forward term
        self.transient_start: float = 0

        self._data_mapping: dict[str, CallbackDataMapping] = {
            "star_tracker_1": CallbackDataMapping(
                callback=self._on_star_tracker_data,
                dataclass=StarTrackerData,
                od_indices=(
                    "orientation_time_since_midnight",
                    "orientation_attitude_known",
                    "orientation_attitude_i",
                    "orientation_attitude_j",
                    "orientation_attitude_k",
                    "orientation_attitude_real",
                ),
            ),
            "adcs": CallbackDataMapping(
                callback=self._on_imu_data,
                dataclass=IMUData,
                od_indices=("gyroscope_pitch_rate", "gyroscope_yaw_rate", "gyroscope_roll_rate"),
            ),
            "gps": CallbackDataMapping(
                callback=self._on_gps_data,
                dataclass=GPSData,
                od_indices=(
                    "skytraq_ecef_x",
                    "skytraq_ecef_y",
                    "skytraq_ecef_z",
                    "skytraq_ecef_vx",
                    "skytraq_ecef_vy",
                    "skytraq_ecef_vz",
                ),
            ),
        }
        self.last_sensor_time: dict[str, int] = {}
        self._sensor_data: dict[str, TimestampedData] = {}
        self._sensor_data_buffer: dict[str, TimestampedData] = {}
        self._sensor_data_valid_buffer: dict[str, dict[str, bool]] = {}

    def on_start(self) -> None:
        # add SDO callbacks, which are also called for relevant PDOs
        # at the same time, initialize valid data tracking and sensor times
        logger.debug("Initializing sensor data mappings...")
        for k, v in self._data_mapping.items():
            self._sensor_data_valid_buffer[k] = {}
            self.last_sensor_time[k] = -1
            for subindex in v.od_indices:
                self._sensor_data_valid_buffer[k][subindex] = False
                self.node.add_sdo_callbacks(
                    k, subindex, None, lambda value, func=v.callback, idx=subindex: func(idx, value)
                )
            logger.debug("Mapping initialized for {}", k)
        logger.debug("Sensor data mappings initialized")
        logger.info("ADCSManager ready")

    @property
    def is_data_available(self) -> bool:
        """Determine if data from all sensors is available

        Returns
        -------
        bool
            True if data is available, False otherwise
        """
        for t in self.last_sensor_time.values():
            if t < 0:
                return False
        return True

    def initialize_filter(self) -> None:
        """Initialize or reset the extended kalman filter"""
        logger.debug("Resetting extended kalman filter")
        omega = self._sensor_data["adcs"].data.gyro
        q = self._sensor_data["star_tracker_1"].data.orientation
        init_time = time()
        # reset filter states for next maneuver TODO: CHECK IF STAR TRACKER WAS AVAILABLE
        self.EKF.reset(q, omega, init_time)

    def update_ECEF_target(self, target_lat, target_lon, target_height) -> None:
        self.ECEF_target = guid.gps_to_ecef(target_lat, target_lon, target_height)

    def on_loop(self) -> None:
        if self.control_mode in ("RW_POINTING", "THERMAL_REORIENT") and not self.filter_initialized:
            if not self.is_data_available:
                sleep(5)
                return
            omega = self._sensor_data["adcs"].data.gyro
            if not self._sensor_data["star_tracker_1"].data.attitude_known:
                d_omega = self.spin_omega_target - omega  # desired delta omega
                # calculate tau, divide by five to smooth control inputs
                tau = self.sat_inertia @ d_omega / self.update_time / 5
                wheel_torque = self.G_pinv @ tau
                # TODO: COMMAND REACTION WHEELS HERE
                logger.debug("Command reaction wheels: {}", wheel_torque)
            else:
                self.initialize_filter()

        if self.guidance_mode in (
            "TARGET",  # track static target on Earth's surface
            "NADIR",
            "MAX_DRAG",  # Orient satellite with largest face ram-pointing (+x)
            "MIN_DRAG",  # Orient satellite with smallest face ram-pointing (+z)
        ):
            """
            Dynamic guidance functions for target tracking, nadir-pointing, and
            minimum & maximum drag orientation. This is separate from the control
            portion of the code, and just defines the target which is fed into the
            control algorithms
            """

            gps_data = self._sensor_data["gps"].data
            r_ecef = np.asarray(gps_data.position)
            v_ecef = np.asarray(gps_data.velocity)
            dt: datetime = datetime.now(timezone.utc) # TODO can use skyfield timelib.now
            t = self.skyfield_timescale.from_datetime(dt)  # set ephemeris calculation time
            eci_2_ecef = self.skyfield_EOP.rotation_at(t)  # inertial -> ECEF rotation matrix
            # used to get correct facing for star tracker
            # Nadir vector is opposite of vector from earth.
            nadir_vector_ecef = -r_ecef / np.linalg.norm(r_ecef)
            if self.guidance_mode == "TARGET":
                # calculate target vector in ECEF cartesian coordinates
                target_vector = self.ECEF_target - r_ecef
                # normalize to unit vector
                target_vector = target_vector / np.linalg.norm(target_vector)
                # create orientation quaternion from cartesian target
                new_target = guid.target_tracking_quat(target_vector, nadir_vector_ecef, eci_2_ecef)
            elif self.guidance_mode == "NADIR":
                # create orientation quaternion from cartesian target
                new_target = guid.nadir_quat(nadir_vector_ecef, v_ecef, eci_2_ecef)
            elif self.guidance_mode == "MAX_DRAG" or self.guidance_mode == "MIN_DRAG":
                # calculate ram-facing orientation for either +z or +x axis based on min or max drag
                new_target = guid.ram_quaternion(
                    self.guidance_mode, v_ecef, nadir_vector_ecef, eci_2_ecef
                )
            else:
                new_target = None
                logger.warning(f"Unknown guidance mode: {self.guidance_mode}")

            self.update_target(new_target)

        if self.control_mode in ("RW_POINTING", "THERMAL_REORIENT"):
            # get sensor data and modify for consumption by control algorithms
            wheel_speeds = (
                np.array(
                    [
                        self.node.od["rw_1"]["motor_velocity"].value,
                        self.node.od["rw_2"]["motor_velocity"].value,
                        self.node.od["rw_3"]["motor_velocity"].value,
                        self.node.od["rw_4"]["motor_velocity"].value,
                    ]
                )
                * 2
                * np.pi
            )
            star_tracker_output: Optional[TimestampedData] = self.get_sensor_data("star_tracker_1")
            omega = self._sensor_data["adcs"].data.gyro
            if star_tracker_output and star_tracker_output.data.attitude_known:
                q_star_tracker = star_tracker_output.data.orientation
                # rotate star tracker output into body frame
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None

            q, omega = self.EKF.update(datetime.now(timezone.utc).timestamp(), omega, q_st_rotated)

            q_last = self.q_target  # save last target for feed-forward terms
            q_error = quat.quat_error(self.q_target, q)
            # only apply hemisphere check once after determining error quaternion to maintain
            # associativity across hemisphere boundaries
            q_error = quat.hemi(q_error)

            """
            The following section includes feed-forward terms for target tracking
            to avoid overdamping and to account for gyroscopic effects 
            """

            # feed forward term for angular rate bias
            # flipped order because of frame conventions for proper signage (body -> target)
            rotation_quat = quat.quat_error(q_last, self.q_target)
            rot_axis = quat.quat_to_axis(rotation_quat)
            rot_angle = quat.error_angle(rotation_quat) * np.pi / 180
            # set rotation rate for tracking maneuver
            omega_desired = rot_axis * (rot_angle / self.update_time)

            # feed forward term to account for stored angular momentum
            # desired acceleration in body frame
            alpha_d_b = (omega_desired - self.omega_desired_prev) / self.update_time
            self.omega_desired_prev = omega_desired.copy()
            # calculate stored wheel momentum in body frame
            # (resulting in a 3x1 vector of angular momentum axis elements in body frame)
            h_wheels = self.rw_inertia * wheel_speeds @ self.G.T
            # total feed-forward torque accounting for gyroscopic coupling
            tau_ff = self.sat_inertia @ alpha_d_b + np.cross(
                omega, self.sat_inertia @ omega + h_wheels
            )

            # set biased omega after using true value to calculate feed forward term
            omega = omega - omega_desired

            # compute desired 3-axis torque from controller
            desired_torque = self.rw_controller(q_error, omega, time())
            desired_torque = desired_torque + tau_ff  # add feedforward terms
            # convert desired 3-axis torque to inputs for 4 reaction wheels
            wheel_torque = self.G_pinv @ desired_torque
            # TODO: COMMAND REACTION WHEELS HERE
            logger.debug("Command reaction wheels: {}", wheel_torque)

            if (
                self.control_mode == "THERMAL_REORIENT"
                and quat.error_angle(q_error) <= 0.1
                and np.all(np.abs(omega) < 1e-6)
            ):
                # TODO: ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS!
                # Must wait for wheels to turn off.
                # They should be at zero by the end of the maneuver. If not, there is a problem!
                # change mission mode to spin-up with magnetorquers
                self.control_mode = "THERMAL_SPINUP"

        elif self.control_mode == "DETUMBLE" or self.control_mode == "THERMAL_DETUMBLE":
            # enter 3-step passive thermal-spin mode by first detumbling with magnetorquers
            omega = self._sensor_data["adcs"].data.gyro
            b = self.get_magnetometer_data()
            # detumble controller as defined by Markley & Crassidis
            desired_torque = self.detumble_gain / (np.linalg.norm(b) ** 2) * np.cross(omega, b)
            # TODO: COMMAND MAGNETORQUERS
            logger.debug("Command Magnetorquers: {}", desired_torque)

            if self.control_mode == "THERMAL_DETUMBLE" and np.all(np.abs(omega) < 1e-4):
                # If angular velocity within threshold, switch to reorient
                self.control_mode = "THERMAL_REORIENT"
                # reset filter as it hasn't been used since reaction wheels last
                self.initialize_filter()

        elif self.control_mode == "THERMAL_SPINUP":
            # spin up about satellite's z-axis using magnetorquer
            omega = self._sensor_data["adcs"].data.gyro
            b = self.get_magnetometer_data()
            if omega[2] < self.thermal_spin_rpm * 2 * np.pi / 60:
                # while satellite is spinning slower than set rate about the z axis, spin up
                tau_des = [0, 0, 1]  # spin about the z axis
                desired_torque = np.cross(b, tau_des) / (b @ b)
                # TODO: COMMAND MAGNETORQUERS
                logger.debug("Command Magnetorquers: {}", desired_torque)

        elif self.control_mode == "MTB_POINTING":
            omega = self._sensor_data["adcs"].data.gyro
            b = self.get_magnetometer_data()
            star_tracker_output: Optional[TimestampedData] = self.get_sensor_data("star_tracker_1")
            if star_tracker_output and star_tracker_output.data.attitude_known:
                q_star_tracker = star_tracker_output.data.orientation
                # rotate star tracker output into body frame
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None

            q, omega = self.EKF.update(datetime.now(timezone.utc).timestamp(), omega, q_st_rotated)
            q_error = quat.quat_error(self.q_target, q)
            # only apply hemisphere check once, after determining error quaternion
            # to maintain associativity across hemisphere boundaries
            q_error = quat.hemi(q_error)

            # desired 3-axis torque in body frame
            tau_des = self.mag_lqr_controller(q_error, omega)
            bm = self._b_mat(b)
            k = 1e-8
            m_cmd = np.linalg.inv(bm.T @ bm + k * np.eye(3)) @ bm.T @ tau_des
            # TODO: COMMAND MAGNETORQUERS
            logger.debug("Command Magnetorquers: {}", m_cmd)

            # TODO: alert C3 ADCS is satisfied. Pause ADCS.
        else:
            logger.error("Unknown control mode {}", self.control_mode)

    def update_target(self, target_quat: np.ndarray) -> None:
        if self.pointing_reference == "ST":
            # define target in body coordinates
            self.q_target = quat.quat_mult(self.q_90_rot, target_quat)
        elif self.pointing_reference == "SC":
            # target does not require rotation
            self.q_target = target_quat
        elif self.pointing_reference == "CFC":
            # define target in body coordinates
            self.q_target = quat.quat_mult(self.q_180_rot, target_quat)
        else:
            logger.error("Unknown pointing reference {}", self.pointing_reference)

    def rw_controller(
        self, q_error: np.ndarray, omega: np.ndarray, current_time: float
    ) -> np.ndarray:
        x = np.concatenate((q_error[:3], omega))

        if self.use_variable_gain and quat.error_angle(q_error) < 1:
            # LQR controller with integral term
            transient_time = 30  # seconds
            if self.gain_mode == 0:
                self.transient_start = current_time
                # switch to transient mode
                self.gain_mode = 1
                # first step of transient mode returns the same as standard controller
                return -self.K_RW @ x
            elif self.gain_mode == 1:
                if self.transient_start >= self.transient_start + transient_time:
                    # switch to full fine-pointing mode
                    self.gain_mode = 2
                gain_switch_time = current_time - self.transient_start
                return (-self.K_RW_fine @ x) * gain_switch_time / transient_time - (
                    self.K_RW @ x
                ) * (1 - gain_switch_time / transient_time)
            else:
                return -self.K_RW_fine @ x
        else:
            # switch to standard gain mode
            self.gain_mode = 0
            return -self.K_RW @ x

    def mag_lqr_controller(self, q_error: np.ndarray, omega: np.ndarray) -> np.ndarray:
        x = np.concatenate((q_error[:3], omega))
        return -self.K_MAG @ x

    @staticmethod
    def _b_mat(b: np.ndarray) -> np.ndarray:
        bx, by, bz = b
        return np.array([[0, bz, -by], [-bz, 0, bx], [by, -bx, 0]])

    def _data_buffer_valid(self, index: str) -> bool:
        """
        Check if the data buffer at an index contains valid data.
        Parameters
        ----------
        index
            The data buffer index.

        Returns
        -------
        bool
            True if the buffer has valid data, else False.

        """
        return all(b for b in self._sensor_data_valid_buffer[index].values())

    @adcs_callback("star_tracker_1")
    def _on_star_tracker_data(
        self, subindex: str, value: Union[bool, float], buf: TimestampedData
    ) -> None:
        if subindex == "orientation_time_since_midnight":
            buf.timestamp = value
        elif subindex == "orientation_attitude_known":
            buf.data.attitude_known = value
        elif subindex == "orientation_attitude_i":
            buf.data.orientation[0] = value
        elif subindex == "orientation_attitude_j":
            buf.data.orientation[1] = value
        elif subindex == "orientation_attitude_k":
            buf.data.orientation[2] = value
        elif subindex == "orientation_attitude_real":
            buf.data.orientation[3] = value
        else:
            logger.error("Received invalid star tracker subindex")

    @adcs_callback("gps")
    def _on_gps_data(self, subindex: str, value: float, buf: TimestampedData) -> None:
        if subindex == "skytraq_time_since_midnight":
            buf.timestamp = value
        elif subindex == "skytraq_ecef_x":
            buf.data.position[0] = value
        elif subindex == "skytraq_ecef_y":
            buf.data.position[1] = value
        elif subindex == "skytraq_ecef_z":
            buf.data.position[2] = value
        elif subindex == "skytraq_ecef_vx":
            buf.data.velocity[0] = value
        elif subindex == "skytraq_ecef_vy":
            buf.data.velocity[1] = value
        elif subindex == "skytraq_ecef_vz":
            buf.data.velocity[2] = value
        else:
            logger.error("Received invalid GPS subindex")

    @adcs_callback("adcs")
    def _on_imu_data(self, subindex: str, value: float, buf: TimestampedData) -> None:
        if subindex == "gyroscope_pitch_rate":
            # Ideally the timestamp would be determined and sent from the card with the IMU
            # but since the ADCS just wants the latest data, this doesn't really get used
            dt = datetime.today()
            ms_since_midnight = (((((dt.hour * 60) + dt.minute) * 60) + dt.second) * 1000) + (
                dt.microsecond // 1000
            )
            buf.timestamp = ms_since_midnight
            buf.data.gyro[0] = value
        elif subindex == "gyroscope_yaw_rate":
            buf.data.gyro[1] = value
        elif subindex == "gyroscope_roll_rate":
            buf.data.gyro[2] = value
        else:
            logger.error("Received invalid IMU subindex")

    def get_magnetometer_data(self) -> np.ndarray:
        """Get field strength data from the magnetometers, in Teslas.

        Returns
        -------
        np.ndarray
            A 1x3 vector of the average of the field strengths of the magnetometers, in Teslas.
        """
        # there are FOUR magnetometers (2 on +Z end card, 2 on -Z)
        # for now the solution is to average their readings
        field_vectors: list = []
        adcs_record: ODRecord = self.node.od["adcs"]
        for direction in ("pos", "min"):
            for num in range(1, 3):
                vec: list[float] = []
                for dim in ("x", "y", "z"):
                    vec.append(adcs_record[f"{direction}_z_magnetometer_{num}_{dim}"].value)
                field_vectors.append(np.array(vec))
        avg = sum(np.array(field_vectors)) / len(field_vectors)
        avg *= 1e-7  # convert milligauss -> Tesla
        return avg

    def get_sensor_data(
        self, sensor: str, default: Optional[TimestampedData] = None
    ) -> Optional[TimestampedData]:
        """Get new sensor data, if it is available.

        Parameters
        ----------
        sensor : str
            the sensor name
        default : Optional[Timestamp]
            The default return value if no new data is available.

        Returns
        -------
        Optional[TimestampedData]
            The sensor data, or None if no new data is available.
        """

        data = self._sensor_data[sensor]
        if data and data.timestamp != self.last_sensor_time[sensor]:
            self.last_sensor_time[sensor] = data.timestamp
            return data
        else:
            return default
