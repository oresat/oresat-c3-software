"""ADCS Service"""

import math
from time import time, sleep, monotonic_ns

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId

from ..subsystems.opd import Opd, OpdNodeId, OpdNode, OpdOctavoNode, OpdState, OpdStm32Node

"""
For node, index, and subindex references, see oresat configs base
"""

class AdcsService(Service):
    """ADCS Service"""

    def __init__(self, config: dict, opd: Opd):
        super().__init__()

        self.od_db = config.od_db
        self.opd = opd
        logger.info("ADCS service object initiated")

    def on_start(self):
        logger.info("Starting ADCS")

        # Calibrate sensors and actuators
        self.gyro_calibrate()
        self.mag_calibrate()
        self.rw_calibrate()

        # Define initial reference frame
        self.init_quat = {"h": 1, "i": 0, "j": 0, "k": 0}
        self.quat = dict(self.init_quat)
        
        # ADCS startup complete
        logger.info("Completed ADCS startup")

    
    def on_loop(self):

        #logger.info("Starting iteration of ADCS loop")
        timestamps = dict()
        start_ns = monotonic_ns()

        # Read sensors
        gyro_values = self.gyro_monitor()
        mag_values = self.mag_monitor()

        # Read actuators
        mt_values = self.mt_monitor()
        self.rw_monitor()


        # Dump data to logger for now
        logger.info(f"gyroscope: {gyro_values}")
        logger.info(f"magnetometers: {mag_values}")
        logger.info(f"magnetorquers: {mt_values}")

        timestamps["sensors_end"] = (monotonic_ns() - start_ns) // 1000
        

        # Determine state (and use filters)
        vect1 = {"x": 1, "y": 0, "z": 0}
        vect2 = {"x": 0, "y": 1, "z": 0}
        theta, rot_vect = self.get_rot_vect(vect1, vect2)
        
        #logger.info(f"Applying rotation of {theta} radians about vector {rot_vect}")
        rot_quat = self.rot_vect_to_quat(theta, rot_vect)
        self.quat = self.quat_product(self.quat, rot_quat)
        #logger.info(f"The current positional quaternion is {self.quat}")

        # Check if positional quaternion is still a unit quaternion
        if abs(math.hypot(*self.quat.values()) - 1) > 0.00000001:
            logger.warning(f"WARNING: positional quaternion is currently not a unit quaternion")
        
        timestamps["state_end"] = (monotonic_ns() - start_ns) // 1000


        # Calculate error


        # Determine control signal


        # Send control signal
        # Control signals turned off for sensor testing, for now
        #self.mt_control()
        #self.rw_control()        
        timestamps["control_end"] = (monotonic_ns() - start_ns) // 1000


        # End of ADCS control loop
        logger.info(f"ADCS loop timestamps are {timestamps} (ms)")
        #logger.info("Completed iteration of ADCS loop")
        sleep(0.1)


    # gyro Functions
    def gyro_calibrate(self):
        #logger.info("Calibrating gyroscopes")
        pass

    def gyro_monitor(self):
        """Monitors the gyroscope"""
        logger.info("Monitoring gyroscope")
        # pitch roll and yaw should be relative to velocity, convert back to xyz
        directions = {"pitch_rate": "x","roll_rate": "y","yaw_rate":"z"}
        gyro_values = dict()
        for name,axis in directions.items():
            gyro_values[axis] = self.od_db["adcs"]["gyroscope"][name].value

        return gyro_values
    
    # MAG Functions
    def mag_calibrate(self):
        """Calibrates the magnetometers"""
        #logger.info("Calibrating Magnetometers")
        pass

    def mag_monitor(self):
        """Monitors the magnetometer readings"""
        logger.info("Monitoring magnetometers")
        # full names are a little long, shorten them for now
        mag_map = {'pos_z_magnetometer_1': 'mag_pz1',
                   'pos_z_magnetometer_2': 'mag_pz2',
                   'min_z_magnetometer_1': 'mag_nz1',
                   'min_z_magnetometer_2': 'mag_nz2',
                   }
        directions = ["x", "y", "z"]
        mag_values = dict()
        for name,nick in mag_map.items():
            mag_values[nick] = dict()
            for axis in directions:
                mag_values[nick][axis] = self.od_db["adcs"][name][axis].value

        return mag_values

    # Magnetorquer Functions
    def mt_calibrate(self):
        """Calibrate magnetorquers"""
        #logger.info("Calibrating magnetorquers")
        pass

    def mt_monitor(self):
        """Monitor magnetorquers"""
        logger.info("Monitoring magnetorquers")
        directions = {"current_x": "x", "current_y": "y", "current_z": "z"}
        cur_values = dict()
        for name,axis in directions.items():
            cur_values[axis] = self.od_db["adcs"]["magnetorquer"][name].value
        return cur_values

    def mt_control(self):
        """Send control signal to magnetorquers"""
        logger.info("Sending control signal to magnetorquers")
        #self.write_sdo('adcs', 'magnetorquer', 'current_z_setpoint', 1) 
        pass

    # Reaction Wheel Functions
    def rw_calibrate(self):
        #logger.info("Calibrating reaction wheels")
        pass

    def rw_monitor(self):
        #logger.info("Monitoring reaction wheels")
        pass

    def rw_control(self):
        #logger.info("Sending control signal to reaction wheels")
        pass

    # HELPER FUNCTIONS
    def write_sdo(self, node, index, subindex, value):
        """Mock function 
        
        Paramters:
        node = the card to write to
        index = the index to write to
        subindex = the subindex to write to
        value = the value to send
        """

        try:
            self.node.sdo_write(node, index, subindex, value)
        except Exception as e:
            logger.warning(f"An error occured with sending SDO: {e}")
            logger.warning(f"node: {node}, index: {index}, subindex: {subindex}, value: {value}")

    def vect_normalize(self, vect: dict):
        """Returns the normalized vector"""
        magnitude = math.hypot(*vect.values())
        norm_vect = dict()
        for key,val in vect.items():
            norm_vect[key] = val / magnitude
        return norm_vect

    def vect_dot_product(self, vect1: dict, vect2: dict):
        """Retuns the value of the dot product between two vectors"""
        return vect1["x"]*vect2["x"] + vect1["y"]*vect2["y"] + vect1["z"]*vect2["z"]

    def vect_cross_product(self, vect1: dict, vect2: dict):
        """Returns a dictionary of the cross product"""
        return {"x": vect1["y"]*vect2["z"] - vect1["z"]*vect2["y"],
                "y": vect1["z"]*vect2["x"] - vect1["x"]*vect2["z"],
                "z": vect1["x"]*vect2["y"] - vect1["y"]*vect2["x"]}

    def get_rot_vect(self, vect1: dict, vect2: dict):
        """Calculates the rotation vector based on two vectors

        Paramters:
        vect1 = dictionary of first vector
        vect2 = dictionary of second vector

        Returns: angle = rotation in radians, vector = normalized vector of rotation"""

        # First, the direction of rotation is the normalized cross product
        vect = self.vect_normalize(self.vect_cross_product(vect1, vect2))
        # Next, find the angle of rotation, use the dot product instead
        angle = math.acos(self.vect_dot_product(vect1,vect2) 
                                  / (math.hypot(*vect1.values())*math.hypot(*vect2.values())))

        return angle, vect

    def rot_vect_to_quat(self, angle: float, vect: dict):
        """Converts rotation vector to quaternion

        Parameters:
        angle = angle in radians
        vect = dictionary of normalized vector {x, y, z}
        
        Return: quaternion = dictionary of normalized quaternion {h, i, j, k}"""

        #logger.debug(f"Converting angle {angle} and vector {vect} into a rotation quaternion")

        #if (vdiff:=abs(math.hypot(*vect.values()) - 1)) > 0.00000001:
        #    logger.warning("WARNING: vector for vector to quaternion conversion is not a unit vector")
        #    logger.warning(f"unit vector diff: {vdiff}")

        quat = {"h": math.cos(angle/2) , 
                "i": math.sin(angle/2)*vect["x"], 
                "j": math.sin(angle/2)*vect["y"], 
                "k": math.sin(angle/2)*vect["z"]}

        #if (qdiff:=abs(math.hypot(*quat.values()) - 1)) > 0.00000001:
        #    logger.warning("WARNING: quaternion conversion did not result in unit quaternion")
        #    logger.warning(f"unit quaternion diff: {qdiff}")
        return quat

    def quat_product(self, quat1, quat2):
        """Calculates the product of two quaternions"""
        # define vectors as quat{i, j, k} -> vect{x, y, z}}
        # Warning! qvect_cross is in the form {x, y, z}
        qvect_cross = self.vect_cross_product(qvect1:={"x": quat1["i"], "y": quat1["j"], "z": quat1["k"]},
                                              qvect2:={"x": quat2["i"], "y": quat2["j"], "z": quat2["k"]})

        # qp = (q.h)(p.h) - dot(q.v,p.v) + (q.h)(p.v) + (p.h)(q.v) + cross(q.v,p.v)
        result_quat = {"h": quat1["h"]*quat2["h"] - self.vect_dot_product(qvect1, qvect2),
                       "i": quat1["h"]*quat2["i"] + quat2["h"]*quat1["i"] + qvect_cross["x"],
                       "j": quat1["h"]*quat2["j"] + quat2["h"]*quat1["j"] + qvect_cross["y"],
                       "k": quat1["h"]*quat2["k"] + quat2["h"]*quat1["k"] + qvect_cross["z"]}

        return result_quat
