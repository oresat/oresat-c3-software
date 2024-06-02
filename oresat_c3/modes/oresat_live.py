"""OreSat Live mode."""

from dataclasses import dataclass
from enum import Enum, unique
from time import monotonic
from typing import ClassVar

from ._mode import Mode, ModeArgs


@unique
class OreSatLiveModeState(Enum):
    STANDBY = 0
    ERROR = 0xFF


@dataclass
class OreSatLiveModeArgs(ModeArgs):

    _BYTES_FMT: ClassVar[str] = "<3i"
    ecef_x: int
    """int32: ECEF X coordinate in cm."""
    ecef_y: int
    """int32: ECEF Y coordinate in cm."""
    ecef_z: int
    """int32: ECEF Z coordinate in cm."""


class OreSatLiveMode(Mode):
    """OreSat Live mode."""

    ARGS = OreSatLiveModeArgs
    CARD = "dxwifi"
    REQUIRED_CARDS = [CARD]

    def on_setup(self):

        # power on cfc cards
        self.enable_nodes([self.CARD])

    def on_run(self):
        return
