"""ADCS Service"""

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
        logger.info("Starting connection to can bus")
        self.network = canopen.Network()
        self.network.connect(channel='vcan0', bustype='socketcan')
        logger.info("Completed connection to can bus")

        logger.info("Iterating through cards")
        self.sys_info = info

        for name,info in self.sys_info.cards.items():
            logger.info(f"Name: {name}, NodeId: {info.node_id}, Processor, {info.processor}")
            
        
        # Scan the network
        self.network.scanner.search()
        sleep(1)
        for node_id in self.network.scanner.nodes:
            logger.info(f"Found node {node_id}")

        logger.info("Completed iteration through cards")


        logger.info("ADCS service object initiated")

    def on_start(self):
        logger.info("Starting ADCS")
        self.imu_calibrate()
        self.mag_calibrate()
        self.rw_calibrate()
        logger.info("Completed ADCS startup")

    def on_loop(self):
        logger.info("Iteration of ADCS loop")
        self.network.send_message(12, 2)
        sleep(1)
        self.rw_monitor()


    def imu_calibrate(self):
        logger.info("Calibrating IMU")
        sleep(1)
        
    def mag_calibrate(self):
        logger.info("Calibrating Magnetometers")
        sleep(1)

    def rw_calibrate(self):
        logger.info("Calibrating reaction wheels")

        logger.info("MOTOR_RESISTANCE_CAL")
        logger.info("MOTOR_INDUCTANCE_CAL")
        logger.info("ENCODER_DIR_CAL")
        logger.info("ENCODER_OFFSET_CAL")
        sleep(1)

    def rw_monitor(self):
        logger.info("Monitoring reaction wheels")
        logger.info("Monitoring rw current_state")
        logger.info("Monitoring rw errors")
        sleep(1)





