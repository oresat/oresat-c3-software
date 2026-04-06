from typing import TypedDict

import numpy as np
from olaf import logger


class ADCSConfig(TypedDict):
    """Config class for the ADCS Manager

    Attributes
    ----------
    g : np.ndarray
        Reaction wheel orientation matrix
    rw_inertia : float
        Reaction wheel moment of inertia about spin axis
    sat_inertia : np.ndarray
        Satellite inertia tensor matrix
    update_time : float
         Controller interval (seconds)
    guidance_mode: str
        Specify *what* the ADCS should point at.

        * ``TARGET``: Tracking a static target on the surface of the earth via GPS coordinates

        * ``NADIR``: Continually face +z nadir (+x as close to ram as possible)

        * ``MAX_DRAG`` and ``MIN_DRAG``: Maximum or minimum drag orientation
    control_mode: str
        Specify what the ADCS is to do. Pointing modes point toward the target specified in
        ``guidance_mode``

        * ``RW_POINTING``: Point toward target specified in `guidance_mode` using the reaction wheels
        * ``MTB_POINTING``: "Magnetic Torque Bar" (magnetorquer) pointing mode
        * ``DETUMBLE``: Coarse detumble with magnetorquers
        * ``THERMAL_DETUMBLE``: First mode in 3-step passive thermal-spin mode:
            1. Coarse detumble with magnetorquers (identical actions to "DETUMBLE" mode)
            2. Enter "THERMAL_REORIENT" to reorient using reaction wheels
            3. Enter "THERMAL_SPINUP" to spin about z-axis using magnetorquers
        * ``THERMAL_REORIENT``: Step 2 in thermal-spin mode (see THERMAL_DETUMBLE)
        * ``THERMAL_SPINUP``: Step 3 in thermal-spin mode (see THERMAL_DETUMBLE)
    pointing_reference: str
        Boresight reference or pointing reference axis of the spacecraft
        (i.e. Selfie Cam or Cirrus Flux Camera). Modes are "SC" and "CFC".
        SENTINEL will only ever use "SC" for the high-gain antenna
    target_lat: float
        Initial target latitude, in degrees
    target_lon: float
        Initial target longitude, in degrees
    target_height: float
        Initial target height, in meters
    orbital_period: float
        The orbital period
    orbital_inclination: float
        The orbital inclination
    star_tracker_uncertainty: float
        :math:`P_{ST0}` , the initial uncertainty of the star tracker attitude, in :math:`rad^2`
    star_tracker_noise: float
        :math:`\sigma_{ST}`, the star tracker measurement noise, in radians
    gyro_uncertainty: float
        :math:`P_{b0}`, the initial gyro bias uncertainty, in rad/s
    gyro_noise: float
        :math:`\sigma_{gyro}`, the gyro white noise, in radians
    gyro_bias_drift: float
        :math:`\sigma_{bias}`, the gyro bias drift / random walk
    use_variable_gain: bool
        Enable/disable gain scheduling for fine pointing
    """

    g: np.ndarray
    rw_inertia: float
    sat_inertia: np.ndarray
    update_time: float
    guidance_mode: str
    control_mode: str
    pointing_reference: str
    target_lat: float
    target_lon: float
    target_height: float
    orbital_period: float
    orbital_inclination: float
    star_tracker_uncertainty: float
    star_tracker_noise: float
    gyro_uncertainty: float
    gyro_noise: float
    gyro_bias_drift: float
    use_variable_gain: bool
    lqr_max_input: float
    lqr_max_error: float
    lqr_max_rate: float


def build_config(mission: str) -> ADCSConfig:
    from .guidance_functions import D2R

    # Create reaction wheels
    # Define 4 reaction wheel unit vectors in a pyramid configuration (60 deg tilt from z-axis)
    z = np.cos(60 * np.pi / 180)  # wheel angle from z axis. Same for all wheels
    xy = np.cos(52.238756 * np.pi / 180)  # wheel angle from x/y axis, sign varies by quadrant

    # wheel moment / orientation matrix
    #  +x+y  +x-y  -x-y  -x+y
    #  motor positions in satellite quadrants. Each column represents one motor's torque components
    g = np.array(([[xy, xy, -xy, -xy], [xy, -xy, -xy, xy], [-z, -z, -z, -z]]))

    rw_inertia = 7.271e-6  # [kg*m^2], moment of inertia about spin axis

    # Inertia tensor data
    if mission == "SENTINEL":

        jxx = 0.01650237
        jxy = 0.00000711
        jxz = 0.00004547
        jyx = jxy
        jyy = 0.015962
        jyz = 0.00003107
        jzx = jxz
        jzy = jyz
        jzz = 0.00651814
    else:
        if mission != "OreSat1":
            logger.warning("Unknown mission: {}, defaulting to OreSat1 config", mission)
        jxx = 0.01650237
        jxy = 0.00000711
        jxz = 0.00004547
        jyx = jxy
        jyy = 0.015962
        jyz = 0.00003107
        jzx = jxz
        jzy = jyz
        jzz = 0.00651814

    # satellite inertia matrix
    j = np.array([[jxx, jxy, jxz], [jyx, jyy, jyz], [jzx, jzy, jzz]])

    sigma_gyro = 0.014 * D2R  # [rad] instantaneous white noise (datasheet gives value in degrees)
    sigma_bias = 1e-5  # slow random bias drift (random walk)
    p_b0 = D2R  # [rad/s] initial gyro uncertainty

    sigma_st = 2.4e-6  # [rad] measurement noise (instantaneous orientation error)
    p_st_0 = 8.7e-7  # [rad^2] initial star tracker attitude uncertainty

    # KSAT coordinates
    target_lat = 78.231500
    target_lon = 15.411100
    target_height = 488  # [m]

    control_mode = "RW_POINTING"

    if "RW" in control_mode:
        # realistic RW sim setup
        fsw_update_time = 0.1
        if fsw_update_time > 2:
            # give user warning about unrealistic time steps so THEY DON'T WASTE TIME
            logger.warning("FSW update time too large for stable convergence with reaction wheels")
    else:
        # realistic MTB sim setup
        fsw_update_time = 10  # suggested fsw rate of no less than 5 seconds for stability

    config: ADCSConfig = {
        "g": g,
        "rw_inertia": rw_inertia,
        "sat_inertia": j,
        "update_time": fsw_update_time,
        "guidance_mode": "TARGET",
        "control_mode": control_mode,
        "pointing_reference": "SC",
        "target_lat": target_lat,
        "target_lon": target_lon,
        "target_height": target_height,
        "orbital_period": 1,
        "orbital_inclination": 1,
        "star_tracker_uncertainty": p_st_0,
        "star_tracker_noise": sigma_st,
        "gyro_uncertainty": p_b0,
        "gyro_noise": sigma_gyro,
        "gyro_bias_drift": sigma_bias,
        "use_variable_gain": False,
    }
    logger.debug("Generated ADCS config: {}", config)
    return config
