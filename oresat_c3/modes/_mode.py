"""All base classes for modes."""

import struct
from enum import IntEnum
from time import monotonic, sleep
from typing import Any, Union

from olaf import MasterNode, logger


class ModeError(Exception):
    """Base Error/Exception for mode errors"""

    pass


class AdcsMode(IntEnum):
    """ADCS modes."""

    STANDBY = 0
    """Standby / do nothing."""
    POINT = 1
    """Point an axis of the satellite towards a ECEF coordinate."""
    BBQ_ROLL = 2
    """Spin the satellite arround the Z axis."""
    DETUMBLE = 3
    """Stop satellite tumble or spin."""


class AdcsPointAxis(IntEnum):
    NONE = 0
    POS_X = 1
    NEG_X = 2
    POS_Y = 3
    NEG_Y = 4
    POS_Z = 5
    NEG_Z = 6


class Mode:
    """
    Base OreSat Mode class.

    All child classes can override on_* methods and MUST override ARGS_FMT with
    the correct struct fmt str.
    See https://docs.python.org/3/library/struct.html#format-characters
    for the struct fmt strs.
    """

    CARDS: list[str] = []
    ADCS_MODE = AdcsMode.STANDBY
    ADCS_AXIS = AdcsPointAxis.NONE
    ARGS_FMT = ""

    def __init__(self, cards: list[str] = [], point_coordinates: list[float] = []):

        self.point_coordinates = point_coordinates
        self.is_done = False
        self.node: MasterNode = None
        self.start_time = 0.0

    def setup(self, node: MasterNode):
        """Setup for the mode."""

        self.node = node
        self.start_time = monotonic()

        try:
            self.on_setup()
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"unexpected exception {e}")

    def on_setup(self):
        """Setup for the mode."""

        pass

    def on_loop(self) -> bool:
        """
        On the loop of the mode.

        Parameters
        ----------
        bool:
            Continue to loop.
        """

        return False

    def end(self):
        """End the task."""

        try:
            self.on_end()
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"unexpected exception {e}")

    def on_end(self):
        """On the end of the mode."""

        pass

    @classmethod
    def validate_args(cls, args: bytes) -> bool:
        return struct.calcsize(cls.ARGS_FMT) == len(args)

    @classmethod
    def parse_args(cls, args: bytes) -> tuple:
        return struct.unpack(cls.ARGS_FMT, args)

    def sdo_read_until(
        self, card: str, index: str, subindex: str, value: Any, delay: float, timeout: float
    ):
        """
        Periodically read the value from an object in another node's OD.

        Parameters
        ----------
        card: str
            Card name to read from.
        index: str
            The index name of object to read.
        subindex: str
            The subindex name of object to read or an empty str or None for no subindex.
        value: Any
            The value to check for.
        delay: float
            Delay in seconds to between checks.
        timeout: float
            Amount of time this function will try to check for the value given in seconds.
            Or 0 for endless.
        """

        start = monotonic()
        while True:
            if timeout > 0 and monotonic() - start < timeout:
                raise TimeoutError()

            try:
                sdo_value = self.node.sdo_read(card, index, subindex)
                if sdo_value == value:
                    break
            except Exception:
                pass

            sleep(delay)
