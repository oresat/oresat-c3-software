import zlib
from time import time

from loguru import logger
from oresat_cand import ManagerNodeClient

from ..gen.c3_od import C3Entry, C3Status
from ..gen.missions import Mission
from . import Service
from .radios import RadiosService

AX25_HEADER_LEN = 16


class BeaconService(Service):
    def __init__(self, node: ManagerNodeClient, radios_service: RadiosService):
        super().__init__(node)

        sat_id = node.od_read(C3Entry.SATELLITE_ID)
        self.mission = Mission.from_id(sat_id)

        self._radios_service = radios_service

    def on_loop(self):
        delay = self.node.od_read(C3Entry.BEACON_DELAY)
        if delay <= 0:
            self.sleep(1)
            return  # do nothing

        tx_enabled = self.node.od_read(C3Entry.TX_CONTROL_ENABLE)
        c3_status = self.node.od_read(C3Entry.STATUS)
        if tx_enabled and c3_status == C3Status.BEACON:
            self.send()

        self.sleep(delay)

    def send(self):
        msg = self.mission.beacon_header
        for entry in self.mission.beacon_body:
            value = self.node.od_read(entry)
            msg += entry.encode(value)
        msg += zlib.crc32(msg[AX25_HEADER_LEN:], 0).to_bytes(4, "little")

        logger.debug("beacon")
        self.node.od_write(C3Entry.BEACON_LAST_TIMESTAMP, int(time()))
        self._radios_service.send_beacon(msg)

    def _on_write_send_now(self, value: bool):
        if value:
            self.send()
