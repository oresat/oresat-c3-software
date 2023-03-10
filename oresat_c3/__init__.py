from enum import Enum

__version__ = '0.1.0'


class C3State(Enum):
    PRE_DEPLOY = ord('B')
    DEPLOY = ord('C')
    STANDBY = ord('D')
    BEACON = ord('E')
    EDL = ord('F')

    @staticmethod
    def from_char(value: str):
        return C3State[ord(value)]

    def to_char(self) -> str:
        return chr(self.value)
