#!/usr/bin/env python3
"""Rudimentary script for calculating ADCS values."""

import pprint
import struct
from math import cos, pi
from typing import TypedDict

from oresat_c3.subsystems.adcs.config import ControlMode, GuidanceMode, PointingReference


class ADCSConfig(TypedDict):
    r"""Config class for the ADCS Manager

    Attributes
    ----------
    g : str
        Reaction wheel orientation matrix, packed to hex string
    rw_inertia : float
        Reaction wheel moment of inertia about spin axis
    sat_inertia : str
        Satellite inertia tensor matrix, packed to hex string
    guidance_mode: GuidanceMode
        Specify *what* the ADCS should point at.

        * ``TARGET``: Tracking a static target on the surface of the earth via GPS coordinates

        * ``NADIR``: Continually face +z nadir (+x as close to ram as possible)

        * ``MAX_DRAG`` and ``MIN_DRAG``: Maximum or minimum drag orientation (+x, +z respectively)
    control_mode: str
        Specify what the ADCS is to do. Pointing modes point toward the target specified in
        ``guidance_mode``

        * ``IDLE``: Do nothing
        * ``RW_POINTING``: Point toward target specified in `guidance_mode` using reaction wheels
        * ``MTB_POINTING``: "Magnetic Torque Bar" (magnetorquer) pointing mode
        * ``DETUMBLE``: Coarse detumble with magnetorquers
        * ``THERMAL_DETUMBLE``: First mode in 3-step passive thermal-spin mode:
            1. Coarse detumble with magnetorquers (identical actions to "DETUMBLE" mode)
            2. Enter "THERMAL_REORIENT" to reorient using reaction wheels
            3. Enter "THERMAL_SPINUP" to spin about z-axis using magnetorquers
        * ``THERMAL_REORIENT``: Step 2 in thermal-spin mode (see THERMAL_DETUMBLE)
        * ``THERMAL_SPINUP``: Step 3 in thermal-spin mode (see THERMAL_DETUMBLE)
    pointing_reference: PointingReference
        Boresight reference or pointing reference axis of the spacecraft
        (i.e. Selfie Cam/Helical or Cirrus Flux Camera).
    target_lat: float
        Initial target latitude, in degrees
    target_lon: float
        Initial target longitude, in degrees
    target_height: float
        Initial target height, in meters
    orbital_period: float
        The orbital period, in seconds
    orbital_inclination: float
        The orbital inclination, in degrees
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
    lqr_max_input: float
        Qualitative value representing the maximum control input during tuning
    lqr_max_error: float
        Qualitative value representing the maximum quaternion error during controller tuning
    lqr_max_rate: float
        Qualitative value representing the maximum body rates during controller tuning
    """

    g: bytes
    rw_inertia: float
    sat_inertia: bytes
    guidance_mode: GuidanceMode
    control_mode: ControlMode
    pointing_reference: PointingReference
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
    lqr_max_input: float
    lqr_max_error: float
    lqr_max_rate: float


def build_config(mission: str) -> ADCSConfig:
    from oresat_c3.subsystems.adcs.guidance_functions import D2R

    # Create reaction wheels
    # Define 4 reaction wheel unit vectors in a pyramid configuration (60 deg tilt from z-axis)
    z = cos(60 * pi / 180)  # wheel angle from z axis. Same for all wheels
    xy = cos(52.238756 * pi / 180)  # wheel angle from x/y axis, sign varies by quadrant

    # wheel moment / orientation matrix
    #  +x+y  +x-y  -x-y  -x+y
    #  motor positions in satellite quadrants. Each column represents one motor's torque components
    g_packed = struct.pack(">ffffffffffff", xy, xy, -xy, -xy, xy, -xy, -xy, xy, -z, -z, -z, -z)

    rw_inertia = 7.271e-6  # [kg*m^2], moment of inertia about spin axis

    # Inertia tensor data
    if mission == "SENTINEL1":
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
            print(f"Unknown mission: {mission}, defaulting to OreSat1 config")
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
    j_packed = struct.pack(">fffffffff", jxx, jxy, jxz, jyx, jyy, jyz, jzx, jzy, jzz)

    sigma_gyro = 0.014 * D2R  # [rad] instantaneous white noise (datasheet gives value in degrees)
    sigma_bias = 1e-5  # slow random bias drift (random walk)
    p_b0 = D2R  # [rad/s] initial gyro uncertainty

    sigma_st = 2.4e-6  # [rad] measurement noise (instantaneous orientation error)
    p_st_0 = 8.7e-7  # [rad^2] initial star tracker attitude uncertainty

    # KSAT coordinates
    target_lat = 78.231500
    target_lon = 15.411100
    target_height = 488  # [m]

    config: ADCSConfig = {
        "g": g_packed.hex(),
        "rw_inertia": rw_inertia,
        "sat_inertia": j_packed.hex(),
        "guidance_mode": "TARGET",
        "control_mode": ControlMode.IDLE,
        "pointing_reference": PointingReference.CIRRUS_FLUX,
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
        "lqr_max_input": 0.001,
        "lqr_max_error": 1,
        "lqr_max_rate": 0.09,
    }
    return config


if __name__ == "__main__":
    conf = build_config("OreSat1")
    pprint.pp(conf)
