import threading
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from queue import SimpleQueue, Empty
from typing import Tuple, Callable

from spacepackets.uslp import TransferFrame, BypassSequenceControlFlag, ProtocolCommandFlag

from oresat_c3.protocols.edl_packet import EdlVcid
from oresat_c3.protocols.uslp import Gvcid


class CopService:

    def __init__(self) -> None:
        self._thread: threading.Thread = threading.Thread(target=self.worker)
        self._signals: SimpleQueue[object] = SimpleQueue()
        # from lower procedures
        self._recv_buffer: SimpleQueue[TransferFrame] = SimpleQueue()
        # to higher procedures
        self._out_buffer: SimpleQueue[TransferFrame] = SimpleQueue()
        self._callbacks: list[Callable[[object], None]] = []

    def notify(self, what: object) -> None:
        self._signals.put(what)

    def buffer_put(self, frame: TransferFrame) -> None:
        self._recv_buffer.put(frame)

    def worker(self) -> None:
        raise NotImplemented

    def register_callback(self, cb: Callable[[object], None]) -> None:
        self._callbacks.append(cb)

    def _callback(self, indication: object) -> None:
        for cb in self._callbacks:
            cb(object)


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

    @dataclass
    class FduArrivedIndication:
        gvcid: int

    @dataclass
    class ValidFrameArrivedIndication:
        """Indicate from a lower procedure that a valid Transfer Frame has been placed in the
        buffer.

        Parameters
        ----------
        gvcid: int
            The Global Virtual Channel Identifier for the frame
        """
        gvcid: int

    def __init__(self, w: int, pw: int, nw: int, allow_retransmission: bool = True) -> None:
        super().__init__()
        self.state: Farm1.FarmState = Farm1.FarmState.OPEN
        self.lockout: bool = False
        self.wait: bool = False
        self.retransmit: bool = False
        self.receiver_frame_sequence_number: int = 0
        self.b_counter: int = 0
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
            if not 1 <= w <= 256:
                raise ValueError("1 <= W <= 256 must be true if retransmission is disallowed")
            if not pw <= w:
                raise ValueError("PW <= W must be true if retransmission is disallowed")
            if not 1 <= pw <= 256:
                raise ValueError("1 <= PW <= 256 must be true if retransmission is disallowed")
            if not nw >= 0:
                raise ValueError("Negative window must be positive")

            self.sliding_window_width = w
            self.positive_window_width = pw
            self.negative_window_width = nw

        self._thread.start()

    def worker(self) -> None:
        while True:
            try:
                notif = self._signals.get_nowait()
            except Empty:
                return
            if isinstance(notif, Farm1.ValidFrameArrivedIndication):
                frame = self._recv_buffer.get()
                self._process_frame(frame)
            else:
                raise TypeError("Unknown Farm1 signal indication type")

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
        return (
            (self.receiver_frame_sequence_number + self.positive_window_width - 1)
            < sequence_num
            < (self.receiver_frame_sequence_number - self.negative_window_width)
        )

    def inside_window(self, sequence_num: int):
        if sequence_num == self.receiver_frame_sequence_number:
            # first case
            # accept the frame
            pass
        elif self.receiver_frame_sequence_number < sequence_num <= self.receiver_frame_sequence_number + self.positive_window_width - 1:
            # second case
            # in the window, seq num is incorrect
            # discard and set retransmit_flag
            self.retransmit = True
        elif self.receiver_frame_sequence_number > sequence_num >= self.receiver_frame_sequence_number - self.negative_window_width:
            pass
            # third case
            # transfer frame is discarded
            # no other actions are taken
        else:
            pass  # TODO: ERROR!

    def _process_frame(self, frame: TransferFrame) -> None:
        if frame.header.bypass_seq_ctrl_flag == BypassSequenceControlFlag.EXPEDITED_QOS:
            if frame.header.prot_ctrl_cmd_flag == ProtocolCommandFlag.USER_DATA:
                pass  # Type-BD, bypass COP
                self._out_buffer.put(frame)
                gvcid = Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                self._callback(self.FduArrivedIndication(gvcid))
            else:
                # Type-BC, check commands
                data = frame.tfdf.tfdz
                directive = data[0]
                if directive == 0x00:
                    # E7 valid unlock
                    self.b_counter = self.b_counter + 1 % 4
                    self.retransmit = False
                    if self.state == Farm1.FarmState.WAIT:
                        self.wait = False
                    if self.state == Farm1.FarmState.LOCKOUT:
                        self.wait = False
                        self.lockout = False
                    self.state = Farm1.FarmState.OPEN
                elif directive == 0x82 and data[1] == 0:
                    # E8 valid Set V(R)
                    self.b_counter = self.b_counter + 1 % 4
                    if self.state == Farm1.FarmState.OPEN:
                        self.retransmit = False
                        self.receiver_frame_sequence_number = data[2]
                    elif self.state == Farm1.FarmState.WAIT:
                        self.retransmit = False
                        self.wait = False
                        self.receiver_frame_sequence_number = data[2]
                        self.state = Farm1.FarmState.OPEN
                else:
                    print("FARM-1: invalid Type-BC directive. Discarding frame")


class VirtualChannel:
    CHANNELS: dict[EdlVcid, Tuple[CopService, Callable]] = {}

    @classmethod
    def register(cls, vcid: EdlVcid, service: CopService, callback) -> None:
        cls.CHANNELS[vcid] = (service, callback)
