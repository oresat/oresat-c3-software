"""'
Beacon Service

Handles the beaconing.
"""

import socket
import zlib
from time import time

from olaf import Service, logger, scet_int_from_time

from .. import C3State
from ..protocols.ax25 import ax25_pack


class BeaconService(Service):
    _DOWNLINK_ADDR = ("localhost", 10015)

    def __init__(self, beacon_def: dict):
        super().__init__()

        self._beacon_def = beacon_def
        logger.info(f"Beacon socket: {self._DOWNLINK_ADDR}")
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP client
        self._ts = 0.0

    def on_start(self):
        beacon_rec = self.node.od["beacon"]

        # objects
        self._c3_state_obj = self.node.od["status"]
        self._tx_enabled_obj = self.node.od["tx_control"]["enable"]
        self._delay_obj = beacon_rec["delay"]

        # contants
        self._dest_callsign = beacon_rec["dest_callsign"].value
        self._src_callsign = beacon_rec["src_callsign"].value
        self._start_chars = beacon_rec["start_chars"].value.encode()

        self.node.add_sdo_callbacks("beacon", "send_now", None, self._on_write_send_now)
        self.node.add_sdo_callbacks("beacon", "last_timestamp", self._on_read_last_ts, None)

    def on_loop(self):
        if self._delay_obj.value <= 0:
            self.sleep(1)
            return  # do nothing

        if self._tx_enabled_obj.value and self._c3_state_obj.value == C3State.BEACON:
            self._send_beacon()

        self.sleep(self._delay_obj.value)

    def _send_beacon(self):
        payload = bytes()
        for obj in self._beacon_def:
            payload += obj.encode_raw(obj.value)
        payload += zlib.crc32(payload, 0).to_bytes(4, "little")

        packet = ax25_pack(
            dest=self._dest_callsign,
            dest_ssid=0,
            src=self._src_callsign,
            src_ssid=0,
            control=3,
            pid=0xF0,
            payload=payload,
        )

        logger.debug("beaconing")
        self._ts = time()
        self._socket.sendto(packet, self._DOWNLINK_ADDR)

    def _on_read_last_ts(self) -> int:
        """SDO read callback to get the SCET timestamp of the last beacon."""

        return scet_int_from_time(self._ts)

    def _on_write_send_now(self, value: bool):
        """SDO write callback to send a beacon immediately."""

        if value:
            self._send_beacon()
