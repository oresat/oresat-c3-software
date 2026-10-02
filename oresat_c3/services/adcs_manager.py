"""
ADCS Manager Service

Handles collecting sensor data from the Star Tracker, IMU, magnetometers, and GPS. Using this data,
it can calculate attitude adjustments and execute those adjustments by commanding reaction wheels
and magnetorquers.
"""

from __future__ import annotations

import functools
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import time
from typing import Callable, Optional, Tuple, Type, TypeVar, Union

import numpy as np
from canopen.objectdictionary import ODRecord, ODVariable
from olaf import Service, logger
from skyfield.api import load
from skyfield.framelib import itrs
from typing_extensions import Concatenate, ParamSpec

from ..subsystems.adcs import guidance_functions as guid
from ..subsystems.adcs import quaternion as quat
from ..subsystems.adcs.config import ControlMode, GainMode, GuidanceMode, PointingReference
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
    od_indices: Tuple[str, ...]


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
    def __init__(self) -> None:
        super().__init__()
        self.control_mode: ODVariable | None = None
        self.guidance_mode: ODVariable | None = None
        self.pointing_reference: ODVariable | None = None
        self.ECEF_target: np.ndarray = np.zeros(3)

        self.update_time: ODVariable | None = None

        self.rw_inertia: ODVariable | None = None
        self.sat_inertia: np.ndarray = np.zeros((3, 3))

        self.g_transpose: np.ndarray = np.zeros((4, 3))
        self.g_pinv: np.ndarray = np.zeros((3, 4))
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

        self.use_variable_gain: ODVariable | None = None
        self.K_RW: np.ndarray = np.empty(3)

        self._gain_mode: GainMode = GainMode.STANDARD

        self.K_RW_fine: np.ndarray = np.empty(3)

        self.K_MAG: np.ndarray = np.empty(3)

        # gain based on minimal principal moment of inertia as defined in Markley & Crassidis
        self.detumble_gain: float = 1.0

        star_tracker_uncertainty: float = 8.7e-07
        star_tracker_noise: float = 2.4e-06
        gyro_uncertainty: float = 0.017453292519943295
        gyro_noise: float = 0.0002443460952792061
        gyro_bias_drift: float = 1e-05
        self.EKF: MEKF = MEKF(
            star_tracker_uncertainty,
            star_tracker_noise,
            gyro_uncertainty,
            gyro_noise,
            gyro_bias_drift,
        )

        # rad/s rate at which to stop detumbling for the vector length
        # note that 0.001 rad/s is about 0.057 deg/s
        self.detumble_norm_threshold = 1e-3
        # rad/s rate at which to stop detumbling for each component
        # note that 0.0001 rad/s is about 0.0057 deg/s
        self.detumble_comp_threshold = 1e-4

        self.skyfield_timescale = load.timescale()
        # Earth Orientation Parameters
        # TODO: UPDATE THIS TO POINT TO ACTUAL FILE
        #  IMPORTANT TO UPDATE, SENSITIVE TO ERRORS OVER TIME
        # Note: ITRS is also used in guidance_functions
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

        # constants for each magnetorquer axis used to convert desired torques to current [uA]
        # To be used in the format: Amps = tau[k]/(K[k]*B*windings[k]*area[k])
        rod_windings = 1700
        OD = 10.5e-3  # outer diameter of windings
        ID = 6.35e-3  # inner diameter of windings
        rod_area = np.pi * ((OD + ID) / 2) ** 2
        rod_length = 71e-3
        # [m] radius of just the core, used to determine the magnetic permeability of permalloy rod
        rod_radius = 6.35e-3 / 2
        rod_mu = 100000  # relative permeability of the core material
        rod_ratio = rod_length / rod_radius
        S_mag = (4 * (np.log(rod_ratio) - 1)) / ((rod_ratio) ** 2 - 4 * np.log(rod_ratio))
        K_rod = 1 + (rod_mu - 1) / (1 + (rod_mu - 1) * S_mag)  # magnetic permeability

        ring_windings = 505
        ring_area = 0.088**2 - (2 * ((0.0845 - 0.0604) / 2) ** 2)
        K_ring = 1  # air-core magnetorquer has magnetic permeability of 1

        # TODO: at some point, the current saturation should be
        # enforced via a dipole software saturation
        # [Equation] amps = dipole / (permeability * windings * area) = dipole * mag_constants

        self.mag_constants = 1e-6 * np.array(
            [
                1 / (K_rod * rod_windings * rod_area),
                1 / (K_rod * rod_windings * rod_area),
                1 / (K_ring * ring_windings * ring_area),
            ]
        )  # constants for each magnetorquer axis used to convert desired torques to current [uA]

    def on_start(self) -> None:
        self.control_mode = self.node.od["adcs_manager"]["control_mode"]
        self.guidance_mode = self.node.od["adcs_manager"]["mode"]
        self.pointing_reference = self.node.od["adcs_manager"]["pointing_reference"]
        # used for tracking mode to set static ground target with GPS coordinates in ECEF
        self.node.add_sdo_callbacks("adcs_manager", "target_lat", None, self._update_ecef_target)
        self.node.add_sdo_callbacks("adcs_manager", "target_lon", None, self._update_ecef_target)
        self.node.add_sdo_callbacks("adcs_manager", "target_height", None, self._update_ecef_target)
        self._update_ecef_target(0.0)

        self.update_time = self.node.od["adcs_manager"]["update_interval"]
        self.node.add_sdo_callbacks("adcs_manager", "update_interval", None, self._update_interval)

        self.node.add_sdo_callbacks("adcs_manager", "sat_inertia", None, self._update_sat_inertia)
        self.rw_inertia = self.node.od["adcs_manager"]["rw_inertia"]
        self._update_sat_inertia(self.node.od["adcs_manager"]["sat_inertia"].value)

        self.node.add_sdo_callbacks(
            "adcs_manager", "rw_orientations", None, self._update_rw_orientations
        )
        self.use_variable_gain = self.node.od["adcs_manager"]["variable_gain"]
        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_input", None, self._update_lqr_rw)
        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_error", None, self._update_lqr_rw)
        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_rate", None, self._update_lqr_rw)
        self._update_lqr_rw(0.0)

        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_input_mag", None, self._update_lqr_mag)
        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_error_mag", None, self._update_lqr_mag)
        self.node.add_sdo_callbacks("adcs_manager", "lqr_max_rate_mag", None, self._update_lqr_mag)

        self._update_lqr_rw_fine()

        self.node.add_sdo_callbacks(
            "adcs_manager", "orbital_period", None, self._update_detumble_gain
        )
        self.node.add_sdo_callbacks(
            "adcs_manager", "orbital_inclination", None, self._update_detumble_gain
        )
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
        return len(self._sensor_data) == len(self._data_mapping)

    def initialize_filter(self) -> None:
        """Initialize or reset the extended kalman filter"""
        logger.debug("Resetting extended kalman filter")
        imu_data = self._sensor_data["adcs"].data
        if not isinstance(imu_data, IMUData):
            logger.error("Incorrect sensor data type")
            self.sleep_ms(5000)
            return
        omega = imu_data.gyro
        q = self._sensor_data["star_tracker_1"].data.orientation
        init_time = time()
        # reset filter states for next maneuver
        self.EKF.reset(q, omega, init_time)
        self.filter_initialized = True

    def _update_sat_inertia(self, value: bytes) -> None:
        jxx, jxy, jxz, jyx, jyy, jyz, jzx, jzy, jzz = struct.unpack(">fffffffff", value)
        self.sat_inertia = np.array([[jxx, jxy, jxz], [jyx, jyy, jyz], [jzx, jzy, jzz]])
        self._update_lqr_rw(1.0)
        self._update_lqr_rw_fine()
        self._update_lqr_mag(1.0)
        self._update_detumble_gain(1.0)

    def _update_rw_orientations(self, value: bytes) -> None:
        logger.debug(value.hex())
        a_1, a_2, a_3, a_4, b_1, b_2, b_3, b_4, c_1, c_2, c_3, c_4 = struct.unpack(
            ">ffffffffffff", value
        )
        g = np.array(([[a_1, a_2, a_3, a_4], [b_1, b_2, b_3, b_4], [c_1, c_2, c_3, c_4]]))
        self.g_transpose = g.T
        self.g_pinv = -np.linalg.pinv(g)

    def _update_interval(self, _value: float) -> None:
        self._update_lqr_rw(1.0)
        self._update_lqr_mag(1.0)

    def _update_lqr_rw(self, _value: float) -> None:
        self.K_RW = get_gain_matrix(
            self.sat_inertia,
            self.update_time.value,
            self.node.od["adcs_manager"]["lqr_max_error"].value,
            self.node.od["adcs_manager"]["lqr_max_rate"].value,
            self.node.od["adcs_manager"]["lqr_max_input"].value,
        )

    def _update_lqr_rw_fine(self) -> None:
        # define a fine pointing controller with aggressive error gains
        self.K_RW_fine = get_gain_matrix(self.sat_inertia, self.update_time.value, 0.05, 0.2, 0.01)

    def _update_lqr_mag(self, _value: float) -> None:
        self.K_MAG: np.ndarray = get_gain_matrix(
            self.sat_inertia,
            self.update_time.value,
            self.node.od["adcs_manager"]["lqr_max_error_mag"].value,
            self.node.od["adcs_manager"]["lqr_max_rate_mag"].value,
            self.node.od["adcs_manager"]["lqr_max_input_mag"].value,
        )

    def _update_ecef_target(self, _value: float) -> None:
        self.ECEF_target = guid.gps_to_ecef(
            self.node.od["adcs_manager"]["target_lat"].value,
            self.node.od["adcs_manager"]["target_lon"].value,
            self.node.od["adcs_manager"]["target_height"].value,
        )

    def _update_detumble_gain(self, _value: float) -> None:
        """
        maximum principal moment of inertia
        (Markley & Crassidis defines this with the minimum principal moment of inertia as a safe
        upper bound to avoid instability, but maximum works better)
        """
        j_min: float = np.max(np.linalg.eigvals(self.sat_inertia))
        self.detumble_gain = (
            4
            * np.pi
            / self.node.od["adcs_manager"]["orbital_period"].value
            * (1 + np.sin(self.node.od["adcs_manager"]["orbital_inclination"].value * np.pi / 180))
            * j_min
        )

    def _command_magnetorquer_current(self, desired_current: np.ndarray) -> bool:
        """Send current values to magnetorquers.

        Parameters
        ----------
        desired_current:
            3x1 array of current to send to magnetorquer setpoints (currently uA).

        Returns
        -------
        bool
            Success in commanding all magnetorquers.
        """
        # TODO: before sending SDOs, check if the card handling the
        # SDO request is sending heartbeats
        logger.debug(f"Recieved command to set magnetorquer currents to {desired_current}")

        # check if any value happens to be complex
        # note that if it were complex, it could not be properly rounded
        # for sending it over the CAN bus
        if np.iscomplexobj(desired_current):
            logger.warning("Magnetorquer currents appear to be complex.")
            logger.warning("Setting magnetorquer currents to real components...")
            desired_current = np.real(desired_current)

        # Attempt to send commands to all magnetorquers.
        logger.debug(
            f"About to send the following currents to the magnetorquers: {desired_current}"
        )
        try:
            logger.debug("Sending command to x-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_x_setpoint", desired_current[0])

            logger.debug("Sending command to y-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_y_setpoint", desired_current[1])

            logger.debug("Sending command to z-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_z_setpoint", desired_current[2])

            # once the sdo writes are successful, return to end
            return True
        except Exception as e:
            logger.error(f"Unable to send SDO commands to all magnetorquers: {e}")

        # if it was not sucessful, try to turn them off one at a time
        try:
            logger.debug("Attempting to turn off the x-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_x_setpoint", 0)
        except Exception as e:
            logger.error(f"Unable to send SDO command to turn off x-magnetorquer: {e}")

        try:
            logger.debug("Attempting to turn off the y-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_y_setpoint", 0)
        except Exception as e:
            logger.error(f"Unable to send SDO command to turn off y-magnetorquer: {e}")

        try:
            logger.debug("Attempting to turn off the z-magnetorquer...")
            self.node.sdo_write("adcs", "magnetorquer", "current_z_setpoint", 0)
        except Exception as e:
            logger.error(f"Unable to send SDO command to turn off z-magnetorquer: {e}")

        return False

    def on_loop(self) -> None:
        logger.info("Start of loop on ADCSManager.")

        # TODO: check if the modes have been updated externally

        logger.debug(f"The control mode is {self.control_mode.value}")
        logger.debug(f"The guidance mode is {self.guidance_mode.value}")
        logger.debug(f"The pointing reference is {self.pointing_reference.value}")

        if self.control_mode.value == ControlMode.IDLE:
            self.sleep_ms(30e3)
            return

        if (
            self.control_mode.value in (ControlMode.RW_POINTING, ControlMode.THERMAL_REORIENT)
            and not self.filter_initialized
        ):
            if not self.is_data_available:
                logger.error("Data is not yet available, skipping control loop.")
                self.sleep(5)
                return
            imu_data = self._sensor_data["adcs"].data
            if not isinstance(imu_data, IMUData):
                logger.error("Incorrect sensor data type")
                self.sleep_ms(5000)
                return

            omega = imu_data.gyro
            star_tracker_output = self._sensor_data["star_tracker_1"]
            if (
                star_tracker_output
                and star_tracker_output is not None
                and isinstance(star_tracker_output.data, StarTrackerData)
                and not star_tracker_output.data.attitude_known
            ):
                d_omega = self.spin_omega_target - omega  # desired delta omega
                # calculate tau, divide by five to smooth control inputs
                tau = self.sat_inertia @ d_omega / self.update_time / 5
                wheel_torque = self.g_pinv @ tau
                # TODO: COMMAND REACTION WHEELS HERE
                logger.debug("Command reaction wheels: {}", wheel_torque)
            else:
                self.initialize_filter()

        # Dynamic guidance functions for target tracking, nadir-pointing, and
        # minimum & maximum drag orientation. This is separate from the control
        # portion of the code, and just defines the target which is fed into the
        # control algorithms

        # retrieve IMU data
        # TODO: wrap this in get_sensor_data
        if "adcs" not in self._sensor_data.keys():
            logger.error("ADCS data is not yet in sensor data.")
            logger.error("No data recieved from ADCS yet.")
            self.sleep(5)
            return
        try:
            imu_data = self._sensor_data["adcs"].data
        except Exception as e:
            logger.error(f"Some other ADCS data error occured: {e}")
            self.sleep(5)
            return
        if not isinstance(imu_data, IMUData):
            logger.error("Incorrect sensor data type")
            self.sleep(5)
            return
        omega = imu_data.gyro

        if self.control_mode.value != ControlMode.DETUMBLE:
            # TODO: change this logic so this code block does not need
            # to be before the control modes

            # retreive GPS data
            # TODO: wrap this in get_sensor_data()
            if "gps" not in self._sensor_data.keys():
                logger.error("GPS data is not yet in sensor data.")
                logger.error("No data recieved from GPS yet.")
                self.sleep(5)
                return
            try:
                gps_data = self._sensor_data["gps"].data
            except Exception as e:
                logger.error(f"Some other GPS data error occured: {e}")
                self.sleep(5)
                return
            if not isinstance(gps_data, GPSData):
                logger.error("Incorrect sensor data type")
                self.sleep(5)
                return

            new_target = self.calculate_target_eci(gps_data)
            logger.debug(f"Target eci quaternion is: {new_target}")
            self.update_target(new_target)

        # Control Modes
        if self.control_mode.value in (ControlMode.RW_POINTING, ControlMode.THERMAL_REORIENT):
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
            star_tracker_output = self.get_sensor_data("star_tracker_1")

            if (
                star_tracker_output
                and isinstance(star_tracker_output, StarTrackerData)
                and star_tracker_output.data.attitude_known
            ):
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
            omega_desired = rot_axis * (rot_angle / self.update_time.value)

            # feed forward term to account for stored angular momentum
            # desired acceleration in body frame
            alpha_d_b = (omega_desired - self.omega_desired_prev) / self.update_time.value
            self.omega_desired_prev = omega_desired.copy()
            # calculate stored wheel momentum in body frame
            # (resulting in a 3x1 vector of angular momentum axis elements in body frame)
            h_wheels = self.rw_inertia * wheel_speeds @ self.g_transpose
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
            wheel_torque = self.g_pinv @ desired_torque
            # TODO: COMMAND REACTION WHEELS HERE
            logger.debug("Command reaction wheels: {}", wheel_torque)

            if (
                self.control_mode.value == ControlMode.THERMAL_REORIENT
                and quat.error_angle(q_error) <= 0.1
                and np.all(np.abs(omega) < self.detumble_comp_threshold)
            ):
                # TODO: ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS!
                # Must wait for wheels to turn off.
                # They should be at zero by the end of the maneuver. If not, there is a problem!
                # change mission mode to spin-up with magnetorquers
                self.control_mode.value = ControlMode.THERMAL_SPINUP.value

        elif self.control_mode.value in (ControlMode.DETUMBLE, ControlMode.THERMAL_DETUMBLE):
            # first, check if conditions have been satisfied for regular detumbling
            if (
                self.control_mode.value == ControlMode.DETUMBLE
                and np.linalg.norm(omega) < self.detumble_norm_threshold
            ):
                logger.info(f"DETUMBLE Control Mode satisfied with omega values of {omega}.")
                logger.debug("Attempting to set magnetorquer currents to zero...")
                success = self._command_magnetorquer_current(desired_current=np.array([0, 0, 0]))
                if not success:
                    logger.warning("Unable to turn of magnetorquers")
                    logger.debug("Attempting to set magnetorquer currents to zero one more time...")
                    success = self._command_magnetorquer_current(
                        desired_current=np.array([0, 0, 0])
                    )
                    if not success:
                        logger.error(
                            "Unable to turn of magnetorquers, but exiting DETUMBLE mode anyway."
                        )
                logger.info("Changing control mode from DETUMBLE to IDLE")
                self.control_mode.value = ControlMode.IDLE.value
                return

            # if still detumbling, check the angular speeds
            logger.debug(f"Angular speed values: {omega}")

            # get the magnetic field data and make sure it is good
            b = self.get_magnetometer_data()
            logger.debug(f"Magnetic field values: {b}")
            if np.linalg.norm(b) == 0:
                logger.warning("Magnetic field values are zero.")
                logger.error("Magnetic field values appear to be bogus.")
                self.sleep(5)
                return

            # detumble controller as defined by Markley & Crassidis
            # this equation is for calculating the magnetic dipole
            desired_dipoles = self.detumble_gain / (np.linalg.norm(b) ** 2) * np.cross(omega, b)
            logger.debug(f"Calculated desired dipoles: {desired_dipoles}")

            # send the dipole commands to magnetoruqers
            m_cmd = desired_dipoles * self.mag_constants
            self._command_magnetorquer_current(desired_current=m_cmd)

            # If in the first of 3-step passive thermal-spin mode,
            # go to next mode.
            if self.control_mode.value == ControlMode.THERMAL_DETUMBLE and np.all(
                np.abs(omega) < self.detumble_comp_threshold
            ):
                # If angular velocity within threshold, switch to reorient
                self.control_mode.value = ControlMode.THERMAL_REORIENT.value
                # reset filter as it hasn't been used since reaction wheels last
                self.initialize_filter()

        elif self.control_mode.value == ControlMode.THERMAL_SPINUP:
            # spin up about satellite's z-axis using magnetorquer
            b = self.get_magnetometer_data()
            if omega[2] < self.thermal_spin_rpm * 2 * np.pi / 60:
                # while satellite is spinning slower than set rate about the z axis, spin up
                tau_des = [0, 0, 1]  # spin about the z axis

                # this equation is for the magnetic dipole
                # TODO: check on why detumble gain is not used
                desired_dipoles = np.cross(b, tau_des) / (b @ b)
                # send the dipole commands to magnetoruqers
                m_cmd = desired_dipoles * self.mag_constants
                self._command_magnetorquer_current(desired_current=m_cmd)

        elif self.control_mode.value == ControlMode.MTB_POINTING:
            if "star_tracker_1" not in self._sensor_data.keys():
                logger.error("Star Tracker is not yet in sensor data.")
                logger.error("No data recieved from star tracker yet.")
                self.sleep(5)
                return

            try:
                star_tracker_output = self.get_sensor_data("star_tracker_1")
            except Exception as e:
                logger.error(f"Some other ADCS data error occured for star tracker: {e}")
                self.sleep(5)
                return

            if (
                star_tracker_output
                and star_tracker_output is not None
                and isinstance(star_tracker_output.data, StarTrackerData)
                and star_tracker_output.data.attitude_known
            ):
                logger.debug("Calculating q_st_rotated...")
                q_star_tracker = star_tracker_output.data.orientation
                # rotate star tracker output into body frame
                q_st_rotated = quat.quat_mult(self.q_90_rot, q_star_tracker)
            else:
                q_st_rotated = None

            if q_st_rotated is None:
                logger.error(f"Issue calculating q_st_rotated!")
                logger.debug(f"Star tracker output: {star_tracker_output}")
                if star_tracker_output is not None:
                    logger.debug(f"Star tracker is instance: {isinstance(star_tracker_output, StarTrackerData)}")
                    if isinstance(star_tracker_output.data, StarTrackerData):
                        logger.debug(f"Star tracker attitude known: {star_tracker_output.data.attitude_known}")
                logger.warning("Skipping control loop.")
                self.sleep(1)
                return

            if not self.filter_initialized:
                logger.debug("Initializing filter...")
                self.initialize_filter()
                logger.debug("Filter initialized, continuing to next control loop.")
                return

            # Get the magnetic field data
            b = self.get_magnetometer_data()
            if np.linalg.norm(b) == 0:
                logger.warning("Magnetic field values are zero.")
                logger.error("Magnetic field values appear to be bogus. Skipping control loop.")
                self.sleep(5)
                return


            logger.debug(f"Pre-filtered quaternion: {q_st_rotated}")
            q, omega = self.EKF.update(datetime.now(timezone.utc).timestamp(), omega, q_st_rotated)
            logger.debug(f"Filtered quaternion: {q}")
            q_error = quat.quat_error(self.q_target, q)
            # only apply hemisphere check once, after determining error quaternion
            # to maintain associativity across hemisphere boundaries
            q_error = quat.hemi(q_error)

            logger.debug(f"q_error: {q_error}")
            logger.debug(f"angle error: {quat.error_angle(q_error)}")

            # desired 3-axis torque in body frame
            tau_des = self.mag_lqr_controller(q_error, omega)
            bm = self._b_mat(b)
            k = 1e-8
            desired_dipoles = np.linalg.inv(bm.T @ bm + k * np.eye(3)) @ bm.T @ tau_des
            m_cmd = desired_dipoles * self.mag_constants
            self._command_magnetorquer_current(desired_current=m_cmd)

            # FIXME: check logic going to this state.
            # The magnetic dipoles should be updated continuously.
            # Should it go into idle state only after state conditions are met?

            if (
                quat.error_angle(q_error) <= 0.1
                and np.all(np.abs(omega) < self.detumble_comp_threshold)
            ):
                # TODO: ZERO WHEEL SPEEDS/TURN OFF REACTION WHEELS!
                # Must wait for wheels to turn off.
                # They should be at zero by the end of the maneuver. If not, there is a problem!
                # change mission mode to spin-up with magnetorquers
                logger.debug("MTB_POINTING satisifed!")
                logger.debug("Attempting to set magnetorquer currents to zero...")
                success = self._command_magnetorquer_current(desired_current=np.array([0, 0, 0]))
                if not success:
                    logger.warning("Unable to turn of magnetorquers")
                    logger.debug("Attempting to set magnetorquer currents to zero one more time...")
                    success = self._command_magnetorquer_current(
                        desired_current=np.array([0, 0, 0])
                    )
                    if not success:
                        logger.error(
                            "Unable to turn of magnetorquers, but exiting MTB_POINTING mode anyway."
                        )
                logger.info("Changing control mode from MTB_POINTING to IDLE")
                self.control_mode.value = ControlMode.IDLE.value
                return


        else:
            logger.error("Unknown control mode {}", self.control_mode.value)

    def calculate_target_eci(self, gps_data: np.ndarray) -> None:
        """Calculate the target quat based on gps data."""

        # get position data and check if bogus
        r_ecef = np.asarray(gps_data.position)
        if np.linalg.norm(r_ecef) < 100:
            logger.debug(f"GPS position: {r_ecef}")
            logger.warning("GPS position data appears to be bogus")

        # get velocity data and check if bogus
        v_ecef = np.asarray(gps_data.velocity)
        if np.linalg.norm(v_ecef) < 100:
            logger.debug(f"GPS velocity: {v_ecef}")
            logger.warning("GPS velocity data appears to be bogus")

        # create inertial to ecef rotation matrix,
        # mostly for correcting the face of the star tracker
        eci_2_ecef = self.skyfield_EOP.rotation_at(self.skyfield_timescale.now())

        # Nadir vector is opposite of vector from earth.
        nadir_vector_ecef = -r_ecef / np.linalg.norm(r_ecef)

        # Calculate the target quaternion based on guidance mode
        if self.guidance_mode.value == GuidanceMode.TARGET:
            # calculate target vector in ECEF cartesian coordinates and normalize
            target_vector = self.ECEF_target - r_ecef
            target_vector = target_vector / np.linalg.norm(target_vector)
            # create orientation quaternion from cartesian target
            new_target = guid.target_tracking_quat(target_vector, nadir_vector_ecef, eci_2_ecef)
        elif self.guidance_mode.value == GuidanceMode.NADIR:
            # create orientation quaternion from cartesian target
            new_target = guid.nadir_quat(nadir_vector_ecef, v_ecef, eci_2_ecef)
        elif (
            self.guidance_mode.value == GuidanceMode.MAX_DRAG
            or self.guidance_mode.value == GuidanceMode.MIN_DRAG
        ):
            # calculate ram-facing orientation for either +z or +x axis based on min or max drag
            new_target = guid.ram_quaternion(
                GuidanceMode(self.guidance_mode.value), v_ecef, nadir_vector_ecef, eci_2_ecef
            )
        else:
            new_target = None
            logger.warning(f"Unknown guidance mode: {self.guidance_mode.value}")

        return new_target

    def update_target(self, target_quat: np.ndarray) -> None:
        """Change the target quat based on pointing reference and save it."""
        if self.pointing_reference.value == PointingReference.STAR_TRACKER:
            # define target in body coordinates
            self.q_target = quat.quat_mult(self.q_90_rot, target_quat)
        elif self.pointing_reference.value == PointingReference.HELICAL:
            # target does not require rotation
            self.q_target = target_quat
        elif self.pointing_reference == PointingReference.CIRRUS_FLUX:
            # define target in body coordinates
            self.q_target = quat.quat_mult(self.q_180_rot, target_quat)
        else:
            logger.error("Unknown pointing reference {}", self.pointing_reference)

    def rw_controller(
        self, q_error: np.ndarray, omega: np.ndarray, current_time: float
    ) -> np.ndarray:
        x = np.concatenate((q_error[:3], omega))

        if self.use_variable_gain.value and quat.error_angle(q_error) < 1:
            # LQR controller with integral term
            transient_time = 30  # seconds
            if self._gain_mode == GainMode.STANDARD:
                self.transient_start = current_time
                # switch to transient mode
                self._gain_mode = GainMode.TRANSIENT
                # first step of transient mode returns the same as standard controller
                return -self.K_RW @ x
            elif self._gain_mode == GainMode.TRANSIENT:
                if self.transient_start >= self.transient_start + transient_time:
                    # switch to full fine-pointing mode
                    self._gain_mode = GainMode.FINE_POINTING
                gain_switch_time = current_time - self.transient_start
                return (-self.K_RW_fine @ x) * gain_switch_time / transient_time - (
                    self.K_RW @ x
                ) * (1 - gain_switch_time / transient_time)
            else:
                return -self.K_RW_fine @ x
        else:
            # switch to standard gain mode
            self._gain_mode = GainMode.STANDARD
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
        if not isinstance(buf.data, StarTrackerData):
            return
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
        if not isinstance(buf.data, GPSData):
            return
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
        if not isinstance(buf.data, IMUData):
            return
        if subindex == "gyroscope_pitch_rate":
            # Ideally the timestamp would be determined and sent from the card with the IMU
            # but since the ADCS just wants the latest data, this doesn't really get used
            dt = datetime.today()
            ms_since_midnight = (((((dt.hour * 60) + dt.minute) * 60) + dt.second) * 1000) + (
                dt.microsecond // 1000
            )
            buf.timestamp = ms_since_midnight
            # FIXME: unit mismatch,
            # v1.0 Mag cards report in milli-degrees per second
            # Object dictionary currently assumes it is in deg/s
            # Desired unit is rad/s
            buf.data.gyro[0] = value * np.pi / 180000
        elif subindex == "gyroscope_yaw_rate":
            buf.data.gyro[1] = value * np.pi / 180000
        elif subindex == "gyroscope_roll_rate":
            buf.data.gyro[2] = value * np.pi / 180000
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
                vec = [
                    adcs_record[f"{direction}_z_magnetometer_{num}_{dim}"].value
                    for dim in ("x", "y", "z")
                ]
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
        if data:
            logger.debug(f"Data: {data}")
            logger.debug(f"Data timestamp: {data.timestamp}")
            logger.debug(f"Sensor timestamp for {sensor}: {self.last_sensor_time[sensor]}")
            if data.timestamp == self.last_sensor_time[sensor]:
                logger.warning(f"Data timstamps match, suggesting there is no new data for {sensor}")
        if data and data.timestamp != self.last_sensor_time[sensor]:
            self.last_sensor_time[sensor] = data.timestamp
            return data
        else:
            logger.warning("Issue with data timestamp, returning default value.")
            return default
