from enum import Enum, IntEnum

__version__ = '0.1.0'


class C3State(Enum):
    '''All valid C3 states'''

    OFFLINE = ord('A')
    '''This state is never actually reachable by the device. Reset vector is ``PRE_DEPLOY``.'''
    PRE_DEPLOY = ord('B')
    '''Holding state after deployment of satellite but before deployment of antennas. Ensures a
    minimum amount of time passes before attempting to deploy antennas and going active.'''
    DEPLOY = ord('C')
    '''Antenna deployment state. Attempts to deploy antennas several times before moving to
    Standby.'''
    STANDBY = ord('D')
    '''Satellite is functional but in standby state. Battery level is too low or tx is disabled.'''
    BEACON = ord('E')
    '''Active beaconing state. Broadcasts telemetry packets via radio periodically.'''
    EDL = ord('F')
    '''Currently receiving and/or transmitting engineering data link packets with a ground
    station.'''

    @staticmethod
    def from_char(value: str):
        return C3State[ord(value)]

    def to_char(self) -> str:
        return chr(self.value)


class NodeId(Enum):
    '''All the CANopen Node ID for OreSat boards.'''

    C3 = 0x01
    BATTERY_0 = 0x04
    BATTERY_1 = 0x08
    SOLAR_PANEL_0 = 0x0C
    SOLAR_PANEL_1 = 0x10
    SOLAR_PANEL_2 = 0x14
    SOLAR_PANEL_3 = 0x18
    SOLAR_PANEL_4 = 0x1C
    SOLAR_PANEL_5 = 0x20
    SOLAR_PANEL_6 = 0x24
    SOLAR_PANEL_7 = 0x28
    STAR_TRACKER_0 = 0x2C
    STAR_TRACKER_1 = 0x30
    GPS = 0x34
    ACS = 0x38
    RW_0 = 0x3C
    RW_1 = 0x40
    RW_2 = 0x44
    RW_3 = 0x48
    DXWIFI = 0x4C
    CFC = 0x50

    @staticmethod
    def from_bytes(value: bytes):
        return NodeId(int.from_bytes(value, 'little'))
