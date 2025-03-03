import zlib
from time import time

from loguru import logger
from oresat_libcanopend import NodeClient

from ..gen.beacon import BEACON_DEFS
from ..gen.od import C3Entry, Status
from ..protocols.ax25 import ax25_pack
from . import Service
from .radios import RadiosService


class BeaconService(Service):
    def __init__(self, node: NodeClient, radios_service: RadiosService):
        super().__init__(node)

        mission = node.od_read(C3Entry.MISSION)
        self._beacon_def = BEACON_DEFS[mission]
        self._radios_service = radios_service
        self.node.add_write_callback(C3Entry.BEACON_SEND_NOW, self._on_write_send_now)

    def on_loop(self):
        delay = self.node.od_read(C3Entry.BEACON_DELAY)
        if delay <= 0:
            self.sleep(1)
            return  # do nothing

        if (
            self.node.od_read(C3Entry.TX_CONTROL_ENABLE)
            and self.node.od_read(C3Entry.STATUS) == Status.BEACON
        ):
            self.send()

        self.sleep(delay)

    def send(self):
        payload = bytes()
        for entry in self._beacon_def:
            value = self.node.od_read(entry)
            payload += entry.encode(value)
        payload += zlib.crc32(payload, 0).to_bytes(4, "little")

        packet = ax25_pack(
            self.node.od_read(C3Entry.BEACON_DEST_CALLSIGN),
            self.node.od_read(C3Entry.BEACON_DEST_SSID),
            self.node.od_read(C3Entry.BEACON_SRC_CALLSIGN),
            self.node.od_read(C3Entry.BEACON_SRC_SSID),
            self.node.od_read(C3Entry.BEACON_CONTROL),
            self.node.od_read(C3Entry.BEACON_PID),
            self.node.od_read(C3Entry.BEACON_COMMAND),
            self.node.od_read(C3Entry.BEACON_RESPONSE),
            payload,
        )

        logger.debug("beacon")
        self.node.od_read(C3Entry.BEACON_LAST_TIMESTAMP, time())
        self._radios_service.send_beacon(packet)

    def _on_write_send_now(self, value: bool):
        if value:
            self.send()
