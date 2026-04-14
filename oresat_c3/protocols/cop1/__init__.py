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

    def __init__(
            self,
            w: int,
            pw: int,
            nw: int,
            allow_retransmission: bool = True,
    ) -> None:
        self.state: Farm1.FarmState
        self.lockout_flag: bool
        self.wait_flag: bool
        self.retransmit_flag: bool = False
        self.receiver_frame_sequence_number: int = 0
        self.b_counter: int
        self.positive_window_width: int
        self.negative_window_width: int
        # implementation dependent vars
        self._retransmission_allowed: bool = allow_retransmission
        if self._retransmission_allowed:
            if 2 <= w <= 254:
                raise ValueError("2 <= W <= 254 must be true if retransmission is allowed")
            else:
                self.sliding_window_width = w
            self.positive_window_width = self.negative_window_width = self.sliding_window_width / 2
        else:
            if 1 <= w <= 256:
                raise ValueError("1 <= W <= 256 must be true if retransmission is disallowed")
            else:
                self.sliding_window_width = w
            if not pw <= w:
                raise ValueError("PW <= W must be true if retransmission is disallowed")
            else:
                self.positive_window_width = pw
            if not 1 <= pw <= 256:
                raise ValueError("1 <= PW <= 256 must be true if retransmission is disallowed")

    def positive_window(self) -> Tuple[int, int]:
        # start, end
        return (
                self.receiver_frame_sequence_number,
                self.receiver_frame_sequence_number + (self.sliding_window_width / 2)
                )

    def negative_window(self) -> Tuple[int, int]:
        return (
                self.receiver_frame_sequence_number - 1,
                self.receiver_frame_sequence_number - 1 - (self.negative_window_width / 2)
                )

    def is_outside_window(self, sequence_num: int) -> bool:
        return (self.receiver_frame_sequence_number + self.positive_window_width - 1) < sequence_num < (self.receiver_frame_sequence_number - self.negative_window_width)

    def inside_window(self, sequence_num: int):
        if sequence_num == self.receiver_frame_sequence_number:
            # first case
            # accept the frame
            pass
        elif self.receiver_frame_sequence_number < sequence_num <= self.receiver_frame_sequence_number + self.positive_window_width - 1:
            # second case
            # in the window, seq num is incorrect
            # discard and set retransmit_flag
            self.retransmit_flag = True
        elif self.receiver_frame_sequence_number > sequence_num >= self.receiver_frame_sequence_number - self.negative_window_width:
            pass
            # third case
            # transfer frame is discarded
            # no other actions are taken
        else:
            pass  # TODO: ERROR!

    @property
    def positive_window_width(self) -> int:
        """The positive_window_width property."""
        if self._retransmission_allowed:
            return self.sliding_window_width / 2
        return self._positive_window_width

    @positive_window_width.setter
    def positive_window_width(self, value):
        self._positive_window_width = value

class VirtualChannel:
    def __init__(self, vcid: EdlVcid, cop_service):
        self.vcid: EdlVcid = vcid
        self.cop_service = cop_service

class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1
