import threading
from dataclasses import dataclass
from enum import StrEnum, Enum, unique
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

    def enable(self) -> None:
        self._thread.start()

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
            cb(indication)


class Farm1(CopService):
    class FarmState(StrEnum):
        """The State of FARM-1"""
        OPEN = "S1"
        WAIT = "S2"
        LOCKOUT = "S3"

    @unique
    class FarmAction(Enum):
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

    def __init__(self, w: int, pw: int = 0, nw: int = 0, allow_retransmission: bool = True) -> None:
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
            if not 2 <= w <= 254:
                raise ValueError("2 <= W <= 254 must be true if retransmission is allowed")
            else:
                self.sliding_window_width = w
            self.positive_window_width = self.negative_window_width = int(
                self.sliding_window_width / 2
            )
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

    def _process_frame(self, frame: TransferFrame) -> bool:
        """Process a transfer frame.

        It is assumed, as specified by CCSDS 232.1-B, that any frames
        passed to this method have already passed validation (6.3.2.1 Transfer Frame Validation).

        Parameters
        ----------
        frame : TransferFrame
            The validated transfer frame to process.
        Returns
        -------
        bool
            True if the frame was successfully processed (either 'ACCEPT' action or no action),
            False for 'DISCARD'
        """

        if frame.header.bypass_seq_ctrl_flag == BypassSequenceControlFlag.EXPEDITED_QOS:
            if frame.header.prot_ctrl_cmd_flag == ProtocolCommandFlag.USER_DATA:
                # E6 Type-BD, bypass COP
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
                    return False
        elif frame.header.bypass_seq_ctrl_flag == BypassSequenceControlFlag.SEQ_CTRLD_QOS:
            if frame.header.prot_ctrl_cmd_flag != ProtocolCommandFlag.USER_DATA:
                print("Discarding frame (E9): invalid 'Type-AC' frame")
                return False
            ns: int = frame.header.vcf_count
            vr = self.receiver_frame_sequence_number
            if frame.header.vcf_count == self.receiver_frame_sequence_number:
                # E1 assume buffer is available FIXME: must be bounded for flight
                if self.state == Farm1.FarmState.OPEN:
                    self._out_buffer.put(frame)
                    gvcid = Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                    self._callback(self.FduArrivedIndication(gvcid))
                    self.receiver_frame_sequence_number = vr + 1 % 256
                    self.retransmit = False
                elif self.state == Farm1.FarmState.WAIT:
                    raise Exception(
                        "Invalid state WAIT for E1: Type-AD received despite Wait_Flag ON"
                    )
                elif self.state == Farm1.FarmState.LOCKOUT:
                    print("Discarding frame (E1,S3)")
                    return False
            elif vr < ns <= vr + self.positive_window_width - 1:
                # E3 (second case): in the window, seq num is incorrect
                print(f"Discarding frame (E3,{self.state})")
                if self.state == Farm1.FarmState.OPEN:
                    self.retransmit = True
                return False
            elif vr > ns >= vr - self.negative_window_width:
                # E4 (third case): in negative window. discard, no other actions.
                print("Discarding frame (E4)")
                return False
            elif self.is_outside_window(ns):
                # E5 outside of window
                print("Discarding frame (E5)")
                if self.state != Farm1.FarmState.LOCKOUT:
                    self.lockout = True
                    self.state = Farm1.FarmState.LOCKOUT
                return False
        return True


class VirtualChannel:
    CHANNELS: dict[EdlVcid, Tuple[CopService, Callable]] = {}

    @classmethod
    def register(cls, vcid: EdlVcid, service: CopService, callback) -> None:
        cls.CHANNELS[vcid] = (service, callback)
