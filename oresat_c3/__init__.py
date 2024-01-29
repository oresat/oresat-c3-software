"""C3 OLAF App."""

from enum import Enum, IntEnum

__version__ = "0.2.3"


class C3State(IntEnum):
    """All valid C3 states"""

    OFFLINE = ord("A")
    """This state is never actually reachable by the device. Reset vector is ``PRE_DEPLOY``."""
    PRE_DEPLOY = ord("B")
    """Holding state after deployment of satellite but before deployment of antennas. Ensures a
    minimum amount of time passes before attempting to deploy antennas and going active."""
    DEPLOY = ord("C")
    """Antenna deployment state. Attempts to deploy antennas several times before moving to
    Standby."""
    STANDBY = ord("D")
    """Satellite is functional but in standby state. Battery level is too low or tx is disabled."""
    BEACON = ord("E")
    """Active beaconing state. Broadcasts telemetry packets via radio periodically."""
    EDL = ord("F")
    """Currently receiving and/or transmitting engineering data link packets with a ground
    station."""

    @staticmethod
    def from_char(value: str):
        """Make an object from char value."""
        return C3State(ord(value))

    def to_char(self) -> str:
        """Get char value."""
        return chr(self.value)
