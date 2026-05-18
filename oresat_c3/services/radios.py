"""
Radios Service

Handles interfacing with the radio driver app.
"""

import socket
import time
from queue import SimpleQueue
from typing import TYPE_CHECKING

from gpiod.line import Value
from olaf import Service, logger

from oresat_c3.subsystems._gpio import request_gpio_input, request_gpio_output

from ..drivers.si41xx import Si41xx, Si41xxIfdiv

if TYPE_CHECKING:
    import gpiod


class RadiosService(Service):
    """Radios Service."""

    BEACON_DOWNLINK_ADDR = ("localhost", 10015)
    EDL_UPLINK_ADDR = ("localhost", 10025)
    EDL_DOWNLINK_ADDR = ("localhost", 10016)
    BUFFER_LEN = 1024

    def __init__(self, mock_hw: bool = False):
        """
        Request gpio, initialize radios, add daemons, and create message queue.

        Parameters
        ----------
        mock_hw : bool
            Flag to enable hardware mocking. True if enabled.
        """
        super().__init__()

        self._mock_hw = mock_hw
        if mock_hw:
            self.uhf = Radio()
            self.lband = Radio()
        else:
            self._radio_enable_gpio: gpiod.LineRequest = request_gpio_output(
                "/dev/gpiochip1", 22, "RADIO_ENABLE"
            )
            self.uhf = UHFRadio()
            self.lband = LBandRadio()

        self.node.add_daemon("lband")
        self.node.add_daemon("uhf")

        self.recv_queue: SimpleQueue[bytes] = SimpleQueue()

    def on_start(self):
        """Provide uninterruptible power-on sequence, and bring up radio daemons."""
        logger.info("enabling radio power domain")
        if not self._mock_hw:
            self._radio_enable_gpio.set_value(
                self._radio_enable_gpio.offsets[0], Value.ACTIVE
            )
            time.sleep(0.1)

            logger.info("enabling uhf radio")
            self.uhf.enable()
            time.sleep(0.1)

            logger.info("enabling lband radio")
            self.lband.enable()
        else:
            logger.info("enabling radio power domain")
            logger.info("enabling uhf radio")
            self.uhf.enable()
            logger.info("enabling lband radio")
            self.lband.enable()

        self.node.od["lband"]["synth_relock_count"].value = self.lband.rf_reset_count

        # FIXME: add an OD for UHF TOT clear count

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

        self.node.daemons["uhf"].start()
        self.node.daemons["lband"].start()

    def on_loop(self):
        """Maintain radio health and receive edl requests."""
        if not self.uhf.is_rf_ok():
            logger.error("tot okay was low, resetting radios")
            self.uhf.rf_reset()
            # FIXME: Add OD TOT counter

        lBandOk = self.lband.is_rf_ok()
        self.node.od["lband"]["synth_lock"].value = lBandOk

        if not lBandOk:
            logger.error("si41xx unlocked, resetting lband synth")
            self.lband.rf_reset()
            self.node.od["lband"][
                "synth_relock_count"
            ].value = self.lband.rf_reset_count

        if recv := self._recv_edl_request():
            self.recv_queue.put(recv)

    def on_stop(self):
        """Power down radios and stop daemons."""
        logger.info("disabling radios")
        self.node.daemons["uhf"].stop()
        self.node.daemons["lband"].stop()

        self._beacon_downlink_socket.close()
        self._edl_downlink_socket.close()
        self._edl_uplink_socket.close()

        if not self._mock_hw:
            # power down sequence
            logger.info("disabling uhf radio")
            self.uhf.disable()
            time.sleep(0.1)

            logger.info("disabling lband radio")
            self.lband.disable()
            time.sleep(0.1)

            logger.info("disabling radio power domain")
            self._radio_enable_gpio.set_value(
                self._radio_enable_gpio.offsets[0], Value.INACTIVE
            )
        else:
            logger.info("disabling uhf radio")
            self.uhf.disable()

            logger.info("disabling lband radio")
            self.lband.disable()

            logger.info("disabling radio power domain")

    def send_edl_response(self, message: bytes):
        """
        Send an EDL packet.

        Parameters
        ----------
        message : bytes
            The message to send as a byte string.
        """
        try:
            self._edl_downlink_socket.sendto(message, self.EDL_DOWNLINK_ADDR)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send mess over EDL downlink: {e}")

        logger.debug(f"sent EDL downlink packet: {message.hex(sep=' ')}")

    def send_beacon(self, message: bytes):
        """
        Send a beacon.

        Parameters
        ----------
        message : bytes
            The beacon to beacon.
        """
        try:
            self._beacon_downlink_socket.sendto(message, self.BEACON_DOWNLINK_ADDR)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"failed to send beacon message: {e}")

        logger.debug(f"Sent beacon downlink packet: {message.hex(sep=' ')}")

    def _recv_edl_request(self) -> bytes:
        """
        Recieve an EDL packet.

        Returns
        -------
        bytes
            The EDL packet or empty byte string if nothing is received.
        """
        try:
            message, src = self._edl_uplink_socket.recvfrom(self.BUFFER_LEN)
        except socket.timeout:
            return b""

        logger.debug(f"received EDL uplink packet: {message.hex(sep=' ')} from {src}")

        return message


class Radio:
    def __init__(self):
        self.rf_reset_count = 0

    def enable(self):
        pass

    def disable(self):
        pass

    def is_rf_ok(self) -> bool:
        return True

    def rf_reset(self):
        self.rf_reset_count += 1


class LBandRadio(Radio):
    """Provides production implmentation of the L-band radio subsystem."""

    def __init__(self) -> None:
        """
        Initialize L-band synth and request gpio.

        See Also
        --------
        oresat_c3.drivers.si41xx : Driver for the L-band synth.
        """
        super().__init__()
        self._si41xx = Si41xx(
            sen_pin="LBAND_LO_nSEN",
            sclk_pin="LBAND_LO_SCLK",
            sdata_pin="LBAND_LO_SDATA",
            auxout_pin="LBAND_LO_nLOCKED",
            ref_freq=16_000_000,  # Hz
            if_div=Si41xxIfdiv.DIV1,
            if_n=1616,
            if_r=32,
            mock=False,
        )

        # request gpio pins
        self._si41xx_nlock_gpio: gpiod.LineRequest = request_gpio_input(
            "/dev/gpiochip3", 29, "LBAND_LO_nLOCKED"
        )
        self._lband_enable_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 19, "LBAND_ENABLE"
        )

        # si41xx synth info
        self._relock_count = 0

    def enable(self):
        """
        Enable L-band power domain and start L-band synth.

        Notes
        -----
        The radio power domain must be enabled first.
        """
        self._lband_enable_gpio.set_value(
            self._lband_enable_gpio.offsets[0], Value.ACTIVE
        )

        self._si41xx.start()
        self._relock_count += 1

    def disable(self):
        """Stop L-band synth and disable L-band power domain."""
        self._si41xx.stop()

        self._lband_enable_gpio.set_value(
            self._lband_enable_gpio.offsets[0], Value.INACTIVE
        )

    def is_rf_ok(self) -> bool:
        """
        Report if the L-band radio is ok.

        Returns
        -------
        bool
            True if L-band radio is ok.
        """
        return self._si41xx_locked()

    def rf_reset(self):
        """Reset the L-band synth."""
        # increment reset counter
        super().rf_reset()
        self._si41xx.stop()
        self._si41xx.start()

    def _si41xx_locked(self) -> bool:
        """Check if the L-band synth is locked.

        Returns
        -------
        bool
            True if the L-band is locked.
        """
        # si41xx_nlock is active low
        state = not bool(
            self._si41xx_nlock_gpio.get_value(self._si41xx_nlock_gpio.offsets[0])
        )
        return state


class UHFRadio(Radio):
    """Provides production implmentation of the UHF radio subsystem."""

    # in seconds
    TOT_CLEAR_DELAY = 0.01

    def __init__(self):
        """Request gpio."""
        super().__init__()
        self._uhf_tot_ok_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 25, "UHF_TOT_OK"
        )
        self._uhf_tot_clear_gpio = request_gpio_output(
            "/dev/gpiochip0", 26, "UHF_TOT_CLEAR"
        )
        self._uhf_enable_gpio: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip0", 16, "UHF_ENABLE"
        )

    def enable(self):
        """
        Enable UHF power domain and clear hardware time out timer (TOT).

        Notes
        -----
        The radio power domain must be enabled first.
        """
        self._uhf_enable_gpio.set_value(self._uhf_enable_gpio.offsets[0], Value.ACTIVE)

        # clear timeout timer
        self._uhf_tot_clear()

    def disable(self):
        """Disable the UHF power domain."""
        self._uhf_enable_gpio.set_value(
            self._uhf_enable_gpio.offsets[0], Value.INACTIVE
        )

    def is_rf_ok(self) -> bool:
        """
        Report if UHF radio is ok.

        Returns
        -------
        bool
            True if UHF radio is ok.
        """
        return self._uhf_tot_ok()

    def rf_reset(self):
        """Reset the UHF radio."""
        # increment reset counter
        super().rf_reset()
        self.disable()
        self.enable()

    def _uhf_tot_ok(self) -> bool:
        """
        Check if the hardware timeout timer (TOT) is ok.

        Returns
        -------
        bool
            True if the UHF TOT is ok
        """
        return bool(self._uhf_tot_ok_gpio.get_value(self._uhf_tot_ok_gpio.offsets[0]))

    def _uhf_tot_clear(self):
        """Clear TOT."""
        self._uhf_tot_clear_gpio.set_value(
            self._uhf_tot_clear_gpio.offsets[0], Value.ACTIVE
        )
        time.sleep(self.TOT_CLEAR_DELAY)

        self._uhf_tot_clear_gpio.set_value(
            self._uhf_tot_clear_gpio.offsets[0], Value.INACTIVE
        )
