from enum import IntEnum, StrEnum
from typing import Union, Tuple


class ControlWord:
    pass

class CopService:
    pass

class Farm1(CopService):
    class FarmState(StrEnum):
        """The State of FARM-1"""
        OPEN = "S1"
        WAIT = "S2"
        LOCKOUT = "S3"

    class FarmAction(IntEnum):
        ACCEPT = 0
        DISCARD = 1
        REPORT = 2
        IGNORE = 3

    def __init__(self):
        self.state: FarmState
        self.lockout_flag: bool
        self.wait_flag: bool
        self.retransmit_flag: bool
        self.receiver_frame_sequence_number: int
        self.farm_b_counter: int
        self.farm_sliding_window_width: int  # W
        self.farm_positive_window_width: int  # PW
        self.farm_negative_window_width: int  # NW
        # implementation dependent vars
        self._retransmission_allowed: bool = True
        if self._retransmission_allowed:
            self.farm_positive_window_width = self.farm_negative_window_width = self.farm_sliding_window_width / 2
        elif:
            if (
                    self.farm_positive_window_width > self.farm_sliding_window_width or self.farm_sliding_window_width < 1 or self.farm_sliding_window_width > 256 or self.farm_positive_window_width < 1 or self.farm_positive_window_width > 256
                    ):
                pass  # TODO: error: invalid window widths for when retransmission not allowed


    def positive_window(self) -> Tuple[int, int]:
        # start, end
        return (
                self.receiver_frame_sequence_number,
                self.receiver_frame_sequence_number + (self.farm_sliding_window_width / 2)
                )
    
    def negative_window(self) -> Tuple[int, int]:
        return (
                self.receiver_frame_sequence_number - 1,
                self.receiver_frame_sequence_number - 1 - (self.farm_negative_window_width / 2)
                )

    def is_outside_window(self, sequence_num: int) -> bool:
        return sequence_num > self.receiver_frame_sequence_number + self.positive_window_width - 1 and sequence_num < self.receiver_frame_sequence_number - self.negative_window_width

    def inside_window(self, sequence_num: int):
        if sequence_num == self.receiver_frame_sequence_number:
            # first case
            # accept the frame
            pass
        elif sequence_num > self.receiver_frame_sequence_number and sequence_num <= self.receiver_frame_sequence_number + self.positive_window_width - 1:
            # second case
            # in the window, seq num is incorrect
            # discard and set retransmit_flag
            self.retransmit_flag = True
        elif sequence_num < self.receiver_frame_sequence_number and sequence_num >= self.receiver_frame_sequence_number - self.negative_window_width:
            # third case
            # transfer frame is discarded
            # no other actions are taken
        else:
            pass  # TODO: ERROR!


    @property
    def positive_window_width(self) -> int:
        """The positive_window_width property."""
        if self._retransmission_allowed:
            return self.farm_sliding_window_width / 2
        return self._positive_window_width

    @positive_window_width.setter
    def positive_window_width(self, value):
        self._positive_window_width = value

    def set_w(self, value):
        # W must be EVEN and between 2<=W<=254
        if self._retransmission_allowed:
            clamp(value, 2, 254)
        else:
            # any integer between 1 and 256
            clamp(value, 1, 256)

class VirtualChannel:
    def __init__(self, id: EdlVcid, cop_service):
        self.vcid: EdlVcid = id
        self.cop_service = cop_service

class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1
