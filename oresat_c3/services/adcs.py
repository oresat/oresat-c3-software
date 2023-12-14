"""ADCS Service"""

import math
from time import time, sleep

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId

from ..subsystems.opd import Opd, OpdNodeId, OpdNode, OpdOctavoNode, OpdState, OpdStm32Node

class AdcsService(Service):
    """ADCS Service"""

    def __init__(self, info: dict, opd: Opd):
        super().__init__()

        self._opd = opd

        # Create the canopen network

        logger.info("Iterating through cards")
        self.sys_info = info

        for name,info in self.sys_info.cards.items():
            logger.info(f"Name: {name}, NodeId: {info.node_id}, Processor, {info.processor}")
            

        logger.info("Completed iteration through cards")


        logger.info("ADCS service object initiated")

    def on_start(self):
        logger.info("Starting ADCS")
        self.imu_calibrate()
        self.mag_calibrate()
        self.rw_calibrate()

        self.init_quat = {"h": 1, "i": 0, "j": 0, "k": 0}
        self.quat = dict(self.init_quat)
        logger.info("Completed ADCS startup")

    
    def on_loop(self):
        logger.info("Starting iteration of ADCS loop")
        sleep(0.25)

        # Read sensors
        self.imu_monitor()
        self.mag_monitor()
        self.rw_monitor()

        # Determine state (filter+)
        vect1 = {"x": 1, "y": 0, "z": 0}
        vect2 = {"x": 0, "y": 1, "z": 0}

        #logger.info(str(vect1))
        #logger.info(str(vect2))
        theta, rot_vect = self.get_rot_vect(vect1, vect2)
        
        logger.info(f"Applying rotation of {theta} radians about vector {rot_vect}")
        rot_quat = self.rot_vect_to_quat(theta, rot_vect)
        self.quat = self.quat_product(self.quat, rot_quat)
        logger.info(f"The current positional quaternion is {self.quat}")
        if abs(math.hypot(*self.quat.values()) - 1) > 0.00000001:
            logger.warning(f"WARNING: positional quaternion is currently not a unit quaternion")
        
        # Calculate error

        # Determine control signal

        # Send control signal
        self.mt_control()
        self.rw_control()

        logger.info("Completed iteration of ADCS loop")
        sleep(1)


    # IMU Functions
    def imu_calibrate(self):
        logger.info("Calibrating IMU")
        sleep(0.1)

    def imu_monitor(self):
        """Monitors the imu unit"""
        logger.info("Monitoring IMU")
        sleep(0.1)

    # MAG Functions
    def mag_calibrate(self):
        """Calibrates the magnetometers"""
        logger.info("Calibrating Magnetometers")
        sleep(0.1)

    def mag_monitor(self):
        """Monitors the magnetometer readings"""
        logger.info("Monitoring magnetometers")
        #logger.info(dir(self.node._od_db['adcs']))
        #logger.info(self.node._od_db['adcs']['pos_z_magnetometer_1_x'].value)
        sleep(0.1)


    # Magnetorquer Functions
    def mt_calibrate(self):
        """Calibrate magnetorquers"""
        logger.info("Calibrating magnetorquers")
        sleep(0.1)

    def mt_monitor(self):
        """Monitor magnetorquers"""
        logger.info("Monitoring magnetorquers")
        sleep(0.1)

    def mt_control(self):
        """Send control signal to magnetorquers"""
        logger.info("Sending control signal to magnetorquers")
        self.write_sdo('adcs', 'magnetorquer', 'current_z_setpoint', 1) 
        sleep(0.1)


    # Reaction Wheel Functions
    def rw_calibrate(self):
        logger.info("Calibrating reaction wheels")
        sleep(0.1)

    def rw_monitor(self):
        logger.info("Monitoring reaction wheels")
        sleep(0.1)

    def rw_control(self):
        logger.info("Sending control signal to reaction wheels")
        sleep(0.1)



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

        logger.debug(f"Converting angle {angle} and vector {vect} into a rotation quaternion")

        if (vdiff:=abs(math.hypot(*vect.values()) - 1)) > 0.00000001:
            logger.warning("WARNING: vector for vector to quaternion conversion is not a unit vector")
            logger.warning(f"unit vector diff: {vdiff}")

        quat = {"h": math.cos(angle/2) , 
                "i": math.sin(angle/2)*vect["x"], 
                "j": math.sin(angle/2)*vect["y"], 
                "k": math.sin(angle/2)*vect["z"]}

        if (qdiff:=abs(math.hypot(*quat.values()) - 1)) > 0.00000001:
            logger.warning("WARNING: quaternion conversion did not result in unit quaternion")
            logger.warning(f"unit quaternion diff: {qdiff}")
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
