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
        logger.info("Completed ADCS startup")

    
    def on_loop(self):
        logger.info("Starting iteration of ADCS loop")
        sleep(0.25)

        # Read sensors
        self.imu_monitor()
        self.mag_monitor()
        self.rw_monitor()

        # Determine state (filter+)

        logger.info(str(self.rot_vect_to_quat(0.1, {"x": 1, "y": 0, "z": 0})))
        logger.info(str(self.rot_vect_to_quat(0.1, {"x": 0, "y": 0.707, "z": 0.707})))
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

        logger.info(type(self.node))
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

    
    def rot_vect_to_quat(self, angle: float, vect: dict):
        """Converts rotation vector to quaternion

        Parameters:
        angle = angle in radians
        vect = dictionary of normalized vector {x, y, z}
        """

        logger.info(f"Converting vector {vect} into a rotation quaternion")

        # for now, comparing the square of the length against 1
        if (vdiff:=abs(sum([val**2 for val in vect.values()]) - 1)) > 0.00000001:
            logger.warning("WARNING: vector for vector to quaternion conversion is not a unit vector")
            logger.warning(f"unit vector diff: {vdiff}")

        quat = {"h": math.cos(angle/2) , 
                "i": math.sin(angle/2)*vect["x"], 
                "j": math.sin(angle/2)*vect["y"], 
                "k": math.sin(angle/2)*vect["z"]}

        # for now, comparing teh square of the length against 1
        if (qdiff:=abs(sum([val**2 for val in quat.values()]) -1 )) > 0.00000001:
            logger.warning("WARNING: quaternion conversion did not result in unit quaternion")
            logger.warning(f"unit quaternion diff: {qdiff}")
        return quat
