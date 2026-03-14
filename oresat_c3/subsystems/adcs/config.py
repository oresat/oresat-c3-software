from typing import TypedDict

from numpy.typing import NDArray
import numpy as np

class ADCSConfig(TypedDict):
    g: NDArray
    rw_inertia: float
    sat_inertia: NDArray
    update_time: float
    guidance_mode: str
    control_mode: str
    pointing_reference: str
    target_lat: float
    target_lon: float
    target_height: float
    orbital_period: float | NDArray # TODO
    orbital_inclination: float | NDArray # TODO
    star_tracker_uncertainty: float
    star_tracker_noise: float
    star_tracker_update_rate: float # in seconds
    gyro_uncertainty: float
    gyro_noise: float
    gyro_bias_drift: float


def build_config() -> ADCSConfig:
    # TODO: reduce dependency on Basilisk imports further (likely by precomputation)
    from Basilisk.utilities.macros import D2R
    # Create reaction wheels
    # Define 4 reaction wheel unit vectors in a pyramid configuration (60 deg tilt from z-axis)
    z = np.cos(60 * np.pi / 180)  # wheel angle from z axis. Same for all wheels
    xy = np.cos(52.238756 * np.pi / 180)  # wheel angle from x/y axis, sign varies by quadrant
    
    #  +x+y  +x-y  -x-y  -x+y  (motor positions in satellite quadrants. Each column represents one motor's torque components)
    G = np.array(([[xy, xy, -xy, -xy],
                   [xy, -xy, -xy, xy],
                   [-z, -z, -z, -z]]))  # Wheel moment/orientation matrix
    
    # rw_inertia = 4.2946e-6      # [kg*m^2], moment of inertia about spin axis (old values from OreSat 0.5 wheels)
    rw_inertia = 7.271e-6  # [kg*m^2], moment of inertia about spin axis
    
    # select satellite model attributes
    # satellite = "OreSat1"
    satellite = "SENTINEL"
    
    # select 3D model file
    if satellite == "SENTINEL":
        # Inertia tensor data
        Jxx = 0.01650237
        Jxy = 0.00000711
        Jxz = 0.00004547
        Jyx = Jxy
        Jyy = 0.015962
        Jyz = 0.00003107
        Jzx = Jxz
        Jzy = Jyz
        Jzz = 0.00651814
    else:
        # Inertia tensor data
        Jxx = 0.01650237
        Jxy = 0.00000711
        Jxz = 0.00004547
        Jyx = Jxy
        Jyy = 0.015962
        Jyz = 0.00003107
        Jzx = Jxz
        Jzy = Jyz
        Jzz = 0.00651814
    
    J = np.array([[Jxx, Jxy, Jxz],  # satellite inertia matrix
                  [Jyx, Jyy, Jyz],
                  [Jzx, Jzy, Jzz]])
    
    # sigma_gyro = 0.1 * D2R # instantaneous white noise (datasheet gives value in degrees, convert to radians) (not sure which to use)
    sigma_gyro = 0.014 * D2R # instantaneous white noise (datasheet gives value in degrees, convert to radians) (not sure which to use)
    sigma_bias = 1e-5 # slow random bias drift (random walk)
    P_b0 = D2R # [rad/s] initial gyro uncertainty
    
    sigma_ST = 2.4e-6 # [rad] measurement noise (instantaneous orientation error)
    P_ST_0 = 8.7e-7 # [rad^2] initial star tracker attitude uncertainty
    ST_update_rate = 1.1 # defined in seconds
    
    # KSAT coordinates
    target_lat = 78.231500
    target_lon = 15.411100
    target_height = 488  # [m]
    
    # ESI headquarters coordinates
    # target_lat = 39.608251
    # target_lon = -104.895788
    # target_height = 1716 # [m]
    
    control_mode = "RW_POINTING"
    
    if "RW" in control_mode: # realistic RW sim setup
        fsw_update_time = .1
        if fsw_update_time > 2: # give user warning about unrealistic time steps so THEY DON'T WASTE TIME
            print("\nWARNING: FSW update time too large for stable convergence with reaction wheels\nExiting sim")
            exit()
    elif control_mode == "ORBITS":
        fsw_update_time = 10
    else: # realistic MTB sim setup
        fsw_update_time = 10 # suggested fsw rate of no less than 5 seconds for stability
    
    config: ADCSConfig = {
        "g": G,
        "rw_inertia": rw_inertia,
        "sat_inertia": J,
        "update_time": fsw_update_time,
        "guidance_mode": "TARGET",
        "control_mode": control_mode,
        "pointing_reference": "SC",
        "target_lat": target_lat,
        "target_lon": target_lon,
        "target_height": target_height,
        "orbital_period": 1,
        "orbital_inclination": 1,
        "star_tracker_uncertainty": P_ST_0,
        "star_tracker_noise": sigma_ST,
        "star_tracker_update_rate": ST_update_rate,
        "gyro_uncertainty": P_b0,
        "gyro_noise": sigma_gyro,
        "gyro_bias_drift": sigma_bias,
    }
    print("Generated ADCS config:", config)
    return config
