"""
Radios Service

Handles interfacing with the AX5043 radio driver app.
"""

from abc import ABC, abstractmethod
import socket
from queue import SimpleQueue
from gpiod.line import Value

from olaf import Service, logger
from oresat_c3.subsystems._gpio import request_gpio_output

from ..drivers.si41xx import Si41xx, Si41xxIfdiv

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import gpiod


class RadiosService(Service):
    """Radios Service."""

    BEACON_DOWNLINK_ADDR = ("localhost", 10015)
    EDL_UPLINK_ADDR = ("localhost", 10025)
    EDL_DOWNLINK_ADDR = ("localhost", 10016)
    BUFFER_LEN = 1024
    TOT_CLEAR_DELAY_MS = 10

    def __init__(self, mock_hw: bool = False):
        super().__init__()

        self._mock_hw = mock_hw
        if mock_hw:
            self.radios = MockRadios(runtime=self)
        else:
            self.radios = Radios(runtime=self)

    def on_start(self):
        self.radios.enable()

    def on_loop(self):
        self.radios.maintain_health()
        self.radios.receive_data()

    def on_stop(self):
        self.radios.disable()


class RadioBase(ABC):
    def __init__(self, runtime: RadiosService):
        self._runtime = runtime

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass

    @abstractmethod
    def maintain_health(self):
        pass

    @abstractmethod
    def receive_data(self):
        pass


class Radios(RadioBase):
    def __init__(self, runtime: RadiosService) -> None:
        super().__init__(runtime)

        self._si41xx = Si41xx(
            "LBAND_LO_nSEN",
            "LBAND_LO_SCLK",
            "LBAND_LO_SDATA",
            "LBAND_LO_nLOCKED",
            16_000_000,  # Hz
            Si41xxIfdiv.DIV1,
            1616,
            32,
            mock=False,
        )

        # request gpio pins
        self._si41xx_nlock_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip3", 29, "LBAND_LO_nLOCKED"
        )
        self._uhf_tot_ok_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 25, "UHF_TOT_OK"
        )
        self._uhf_tot_clear_gpio = request_gpio_output(
            "/dev/gpiochip0", 26, "UHF_TOT_CLEAR"
        )
        self._radio_enable_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip1", 22, "RADIO_ENABLE"
        )
        self._uhf_enable_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 16, "UHF_ENABLE"
        )
        self._lband_enable_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 19, "LBAND_ENABLE"
        )

        # si41xx synth info
        self._relock_count = 0

        # beacon downlink: UDP client
        logger.info(f"Beacon socket: {self._runtime.BEACON_DOWNLINK_ADDR}")
        self._beacon_downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # EDL uplink: UDP server
        logger.info(f"EDL uplink socket: {self._runtime.EDL_UPLINK_ADDR}")
        self._edl_uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._edl_uplink_socket.bind(self._runtime.EDL_UPLINK_ADDR)
        self._edl_uplink_socket.settimeout(1)

        # EDL downlink: UDP client
        logger.info(f"EDL downlink socket: {self._runtime.EDL_DOWNLINK_ADDR}")
        self._edl_downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self.recv_queue: SimpleQueue[bytes] = SimpleQueue()

    def enable(self):
        """Enable the radios."""
        self._runtime.node.add_daemon("lband")
        self._runtime.node.add_daemon("uhf")

        logger.info("enabling radio power domain")
        self._radio_enable_gpio.set_value(
            self._radio_enable_gpio.offsets[0], Value.ACTIVE
        )
        self._runtime.sleep_ms(100)

        logger.info("enabling uhf radio")
        self._uhf_enable_gpio.set_value(self._uhf_enable_gpio.offsets[0], Value.ACTIVE)
        self._runtime.sleep_ms(100)

        logger.info("enabling lband radio")
        self._lband_enable_gpio.set_value(
            self._lband_enable_gpio.offsets[0], Value.ACTIVE
        )

        self._uhf_tot_clear()
        self._si41xx.start()
        self._relock_count += 1
        self._runtime.node.od["lband"][
            "synth_relock_count"
        ].value = self._relock_count.bit_length()

        self._runtime.node.daemons["uhf"].start()
        self._runtime.node.daemons["lband"].start()

    def disable(self):
        """Disable radio power domain, UHF, and lband"""

        logger.info("disabling radios")
        self._runtime.node.daemons["uhf"].stop()
        self._runtime.node.daemons["lband"].stop()

        self._si41xx.stop()

        logger.info("disabling lband radio")
        self._lband_enable_gpio.set_value(
            self._lband_enable_gpio.offsets[0], Value.INACTIVE
        )
        self._runtime.sleep_ms(100)

        logger.info("disabling uhf radio")
        self._uhf_enable_gpio.set_value(
            self._uhf_enable_gpio.offsets[0], Value.INACTIVE
        )

        logger.info("disabling radio power domain")
        self._runtime.sleep_ms(100)
        self._radio_enable_gpio.set_value(
            self._radio_enable_gpio.offsets[0], Value.INACTIVE
        )

    def maintain_health(self):
        """Check health of UHF and lband radios, resetting if necessary"""
        if not self._uhf_tot_ok():
            logger.error("tot okay was low, resetting radios")
            self.disable()
            self.enable()

        if not self._si41xx_locked():
            logger.error("si41xx unlocked, resetting lband synth")
            self._relock_count += 1
            self._runtime.node.od["lband"][
                "synth_relock_count"
            ].value = self._relock_count.bit_length()
            self._si41xx.stop()
            self._si41xx.start()

    def _uhf_tot_ok(self) -> bool:
        """bool: check if the UHF TOT is okay."""

        return bool(self._uhf_tot_ok_gpio.get_value(self._uhf_tot_ok_gpio.offsets[0]))

    def _si41xx_locked(self) -> bool:
        """bool: check if the si41xx is locked."""

        # si41xx_nlock is active low
        state = not bool(self._si41xx_nlock_gpio.value)
        self._runtime.node.od["lband"]["synth_lock"].value = state
        return state

    def send_edl_response(self, message: bytes):
        """Send an EDL packet."""

        try:
            self._edl_downlink_socket.sendto(message, self._runtime.EDL_DOWNLINK_ADDR)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send mess over EDL downlink: {e}")

        logger.debug(f"sent EDL downlink packet: {message.hex(sep=' ')}")

    def _uhf_tot_clear(self):
        """Clear TOT."""

        self._uhf_tot_clear_gpio.set_value(
            self._uhf_tot_clear_gpio.offsets[0], Value.ACTIVE
        )
        self._runtime.sleep_ms(self._runtime.TOT_CLEAR_DELAY_MS)
        self._uhf_tot_clear_gpio.set_value(
            self._uhf_tot_clear_gpio.offsets[0], Value.INACTIVE
        )

    def send_beacon(self, message: bytes):
        """Send a beacon."""

        try:
            self._beacon_downlink_socket.sendto(
                message, self._runtime.BEACON_DOWNLINK_ADDR
            )
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send beacon message: {e}")

        logger.debug(f"Sent beacon downlink packet: {message.hex(sep=' ')}")

    def receive_data(self):
        if recv := self._recv_edl_request():
            self.recv_queue.put(recv)

    def _recv_edl_request(self) -> bytes:
        """Recieve an EDL packet."""

        try:
            message, _ = self._edl_uplink_socket.recvfrom(self._runtime.BUFFER_LEN)
        except socket.timeout:
            return b""

        logger.debug(f"received EDL uplink packet: {message.hex(sep=' ')}")

        return message


class MockRadios(RadioBase):
    def enable(self):
        return super().enable()

    def disable(self):
        return super().disable()

    def maintain_health(self):
        return super().maintain_health()

    def receive_data(self):
        return super().receive_data()
