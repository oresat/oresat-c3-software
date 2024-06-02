"""CFC capture mode."""

from dataclasses import dataclass
from enum import Enum, unique
from time import monotonic
from typing import ClassVar

import canopen
from olaf import logger

from ._mode import Mode, ModeArgs


@unique
class CfcCaptureModeState(Enum):
    STANDBY = 0
    CAPTURE = 1
    ERROR = 0xFF


@dataclass
class CfcCaptureArgs(ModeArgs):

    _BYTES_FMT: ClassVar[str] = "<bf?3i"
    capture: int
    """uint8: Number of captures to take."""
    delay: float
    """float: Delay between captures in seconds."""
    tec: bool
    """bool: With or without TEC."""
    ecef_x: int
    """int32: ECEF X coordinate in cm."""
    ecef_y: int
    """int32: ECEF Y coordinate in cm."""
    ecef_z: int
    """int32: ECEF Z coordinate in cm."""


class CfcCaptureMode(Mode):
    """CFC capture mode."""

    ARGS = CfcCaptureArgs
    REQUIRED_CARDS = ["cfc_processor", "cfc_sensor"]
    CARD = "cfc_processor"

    def on_setup(self):

        # power on cfc cards
        self.enable_nodes([self.CARD])

        # wait for camera to leave boot lockout state
        camera_boot_timeout = self.node.od_read("cfc_capture_mode", "boot_timeout")
        tic = monotonic()
        while self.node.sdo_read_enum(self.CARD, "camera", "status") != "off":
            if monotonic() > tic + camera_boot_timeout:
                raise TimeoutError()

        # configure capture sequence
        self.node.sdo_write_enum(self.CARD, "camera", "status", "standby")
        self.node.sdo_write(self.CARD, "camera", "number_to_capture", self.mode_args.captures)
        self.node.sdo_write(self.CARD, "camera", "capture_delay", self.mode_args.delay)
        self.node.sdo_write(self.CARD, "tec", "status", self.mode_args.tec)

    def on_run(self):

        fread_files_before = self.olaf_file_list(self.CARD, "fread")

        # start capture sequence
        self.node.sdo_write(self.CARD, "camera", "status", "capture")

        # wait for camera to leave capture state
        timeout = self.node.od_read("cfc_capture_mode", "standby_timeout")
        tic = monotonic()
        while self.node.sdo_read_enum(self.CARD, "camera", "status") != "standby":
            if monotonic() > tic + timeout:
                raise TimeoutError("cfc did no go into capture mode")
            self.sleep_ms(100)

        # wait for capturing to finish
        timeout = self.node.od_read("cfc_capture_mode", "capture_timeout")
        tic = monotonic()
        while self.node.sdo_read_enum(self.CARD, "camera", "status") != "standby":
            if monotonic() > tic + timeout:
                raise TimeoutError("cfc capture mode has timed out")
            self.sleep_ms(1000)

        self._cleanup()

        # fread all the new captures
        fread_files_after = self.olaf_file_list(self.CARD, "fread")
        for file in fread_files_after - fread_files_before:
            self.olaf_fread(self.CARD, file)

    def on_error(self, error: Exception):

        self._cleanup()

    def _cleanup(self):

        try:
            self.node.sdo_write(self.CARD, "tec", "status", False)
            self.node.sdo_write_enum(self.CARD, "camera", "status", "off")
        except canopen.SdoAbortedError:
            pass
