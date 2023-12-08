"""APDS Service"""

from time import time, sleep

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId

from ..subsystems.opd import Opd, OpdNodeId


class AdcsService(Service):
    """'EDL Service"""
    
    def __init__(self, opd: Opd):
        super().__init__()

        self._opd = opd

        logger.info("ADCS service object initiated")

    def on_start(self):
        logger.info("Starting ADCS")
        logger.info("Completed ADCS startup")

    def on_loop(self):
        logger.info("Iteration of ADCS loop")
        sleep(1)
