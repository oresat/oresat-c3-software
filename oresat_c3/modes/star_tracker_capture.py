"""Star tracker capture mode."""

from dataclasses import dataclass
from enum import Enum, unique
from time import monotonic
from typing import ClassVar

from ._mode import Mode, ModeArgs


@unique
class StarTrackerCaptureState(Enum):
    STANDBY = 0
    START = 1
    CAPTURE = 2
    ERROR = 0xFF


@dataclass
class StarTrackerCaptureArgs(ModeArgs):
    """Star tracker capture mode arguments."""

    _BYTES_FMT: ClassVar[str] = "<2bf3i"
    capture: int
    """uint8: Number of captures to take."""
    delay: float
    """float: Delay between captures in seconds."""
    ecef_x: int
    """int32: ECEF X coordinate in cm."""
    ecef_y: int
    """int32: ECEF Y coordinate in cm."""
    ecef_z: int
    """int32: ECEF Z coordinate in cm."""


class StarTrackerCaptureMode(Mode):
    """Star tracker capture mode."""

    ARGS = OreSatLiveModeArgs
    CARD = "star_tracker"
    REQUIRED_CARDS = [CARD]

    def on_setup(self):

        self.enable_nodes([self.CARD])

        self.node.sdo_write(self.CARD, "camera", "status", "standby")
        self.node.sdo_write(self.CARD, "camera", "num_of_images", self.mode_args.captures)
        self.node.sdo_write(self.CARD, "camera", "delay", self.mode_args.captures)

    def on_loop(self):

        fread_files_before = self.olaf_file_list(self.CARD, "fread")

        self.CARD = f"star_tracker_{self.mode_args.star_tracker}"

        while self.node.sdo_read(self.CARD, "camera", "status") != "booting":
            self.sleep_ms(1000)

        self.node.sdo_write(self.CARD, "camera", "status", "capture")

        while self.node.sdo_read(self.CARD, "camera", "status") == "capture":
            self.sleep_ms(1000)

        # fread all the new captures
        fread_files_after = self.olaf_file_list(self.CARD, "fread")
        for file in fread_files_after - fread_files_before:
            self.olaf_fread(self.CARD, file)
