"""'
Radios Service

Handles interfacing with the AX5043 radio driver app.
"""

import socket
from typing import List

from olaf import Gpio, Service, logger

from ..drivers.si41xx import Si41xx, Si41xxIfdiv


class RadiosService(Service):
    """Radios Service."""

    BEACON_DOWNLINK_ADDR = ("localhost", 10015)
    EDL_UPLINK_ADDR = ("localhost", 10025)
    EDL_DOWNLINK_ADDR = ("localhost", 10016)
    BUFFER_LEN = 1024
    TOT_CLEAR_DELAY_MS = 10

    def __init__(self, mock_hw: bool = False):
        super().__init__()

        self._si41xx = Si41xx(
            "LBAND_LO_nSEN",
            "LBAND_LO_SCLK",
            "LBAND_LO_SDATA",
            "LBAND_LO_nLOCKED",
            16_000_000,  # Hz
            Si41xxIfdiv.DIV1,
            1616,
            32,
            mock=mock_hw,
        )

        # gpio pins
        self._uhf_tot_ok_gpio = Gpio("UHF_TOT_OK", mock_hw)
        self._uhf_tot_clear_gpio = Gpio("UHF_TOT_CLEAR", mock_hw)

        # beacon downlink: UDP client
        logger.info(f"Beacon socket: {self.BEACON_DOWNLINK_ADDR}")
        self._beacon_downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # EDL uplink: UDP server
        logger.info(f"EDL uplink socket: {self.EDL_UPLINK_ADDR}")
        self._edl_uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._edl_uplink_socket.bind(self.EDL_UPLINK_ADDR)
        self._edl_uplink_socket.settimeout(1)

        # EDL downlink: UDP client
        logger.info(f"EDL downlink socket: {self.EDL_DOWNLINK_ADDR}")
        self._edl_downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.recv_queue: List[bytes] = []

    def on_start(self):
        self.uhf_tot_clear()
        self._si41xx.start()

    def on_loop(self):
        if not self.is_uhf_tot_okay:
            self.uhf_tot_clear()

        recv = self._recv_edl_request()
        if recv:
            self.recv_queue.append(recv)

    def on_stop(self):
        self._si41xx.stop()

    def uhf_tot_clear(self):
        """Clear TOT."""

        self._uhf_tot_clear_gpio.high()
        self.sleep_ms(self.TOT_CLEAR_DELAY_MS)
        self._uhf_tot_clear_gpio.low()

    @property
    def is_uhf_tot_okay(self) -> bool:
        """bool: check if the UHF TOT is okay."""

        return bool(self._uhf_tot_ok_gpio.value)

    def send_beacon(self, message: bytes):
        """Send a beacon."""

        try:
            self._beacon_downlink_socket.sendto(message, self.BEACON_DOWNLINK_ADDR)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send beacon message: {e}")

        logger.debug(f'Sent beacon downlink packet: {message.hex(sep=" ")}')

    def _recv_edl_request(self) -> bytes:
        """Recieve an EDL packet."""

        try:
            message, _ = self._edl_uplink_socket.recvfrom(self.BUFFER_LEN)
        except socket.timeout:
            return b""

        logger.debug(f'received EDL uplink packet: {message.hex(sep=" ")}')

        return message

    def send_edl_response(self, message: bytes):
        """Send an EDL packet."""

        try:
            self._edl_downlink_socket.sendto(message, self.EDL_DOWNLINK_ADDR)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send mess over EDL downlink: {e}")

        logger.debug(f'sent EDL downlink packet: {message.hex(sep=" ")}')
