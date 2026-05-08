import logging
import threading
from dataclasses import dataclass
from enum import Enum, unique
from math import ceil

from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag, TransferFrame

from oresat_c3.protocols.cop1.control_word import ControlWord

from ..uslp import Gvcid
from .util import BoundedDeque

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


@dataclass
class Indication:
    """This is the base for COP indications. Sometimes referred to as requests, directives, signals,
    notifications, or indications depending on the context.

    Parameters
    ----------
    gvcid: Gvcid
        The Global Virtual Channel Identifier for the frame
    """

    gvcid: Gvcid


class ServiceInterface:
    """A generic interface to a COP service.

    For example, in an interface to a lower procedure, the lower procedure would insert a frame into
    the buffer and notify the service by inserting a `ValidFrameArrivedIndication`. The COP service
    can then check the signal buffer for signals, and if signaled to process a new frame, fetch from
    the buffer.

    Attributes
    ----------
    buffer : BoundedDeque[TransferFrame]
        The USLP frame buffer for this interface. For example, in an interface to a lower procedure,
        the lower procedure would insert frames and COP would receive them.
    signal : BoundedDeque[Indication]
        The COP-1 standard interchangeably calls these signals, indications, or notifications
        depending on the context.
    """

    def __init__(self, buffer_size: int, signal_size: int = 0) -> None:
        """

        Parameters
        ----------
        buffer_size
            The size of the frame buffer.
        signal_size
            The size of the signal queue. If <= 0, the signal queue will automatically be sized
            as 1.25x the buffer size, to accommodate both frame indications for a full buffer, and
            leave some room for any additional signals (such as aborted indications).
        """

        self.buffer: BoundedDeque[TransferFrame] = BoundedDeque(buffer_size)
        self.signal: BoundedDeque[Indication] = BoundedDeque(
            signal_size if signal_size > 0 else ceil(buffer_size * 1.25)
        )


class FarmHigherServiceInterface(ServiceInterface):
    """A ServiceInterface specifically for FARM-1 higher procedures.

    Attributes
    ----------
    buffer_release
        A threading event that, if set, triggers FARM-1 E10, "Buffer release signal."
        This transitions the FARM-1 state machine out of the wait state on the next tick.
    """

    def __init__(self, buffer_size: int, signal_size: int = 0) -> None:
        super().__init__(buffer_size, signal_size)
        self.buffer_release = threading.Event()


class CopService:
    """An abstraction for COP-1 services (FARM and FOP).

    Attributes
    ----------
    lower_interface: ServiceInterface
        The interface from the lower procedures ("inputs"). The COP service is only expected to
        fetch from this interface.
    higher_interface: ServiceInterface
        The interface to the higher procedures ("outputs"). A COP service is only expected to insert
        into this interface.
    """

    def __init__(self, buffer_size: int = 10) -> None:
        """

        Parameters
        ----------
        buffer_size
            The size of the procedure interface buffers. Given a FOP_SLIDING_WINDOW_WIDTH *K*,
            it is recommended to set `buffer_size` >= K. By default, K=10 in YAMCS.
        """
        # from lower procedures
        self.lower_interface: ServiceInterface = ServiceInterface(buffer_size)
        # to higher procedures
        self.higher_interface: FarmHigherServiceInterface = FarmHigherServiceInterface(buffer_size)

    def tick(self) -> None:
        raise NotImplemented


class Farm1(CopService):
    @unique
    class FarmState(Enum):
        """The State of FARM-1"""

        OPEN = 1
        WAIT = 2
        LOCKOUT = 3

    @unique
    class FarmAction(Enum):
        ACCEPT = 0
        DISCARD = 1
        REPORT = 2
        IGNORE = 3

    @dataclass
    class FduArrivedIndication(Indication):
        pass

    @dataclass
    class ValidFrameArrivedIndication(Indication):
        """Indicate from a lower procedure that a valid Transfer Frame has been placed in the
        buffer.
        """

        pass

    def __init__(
        self,
        w: int,
        pw: int = 0,
        nw: int = 0,
        vcf_count_length: int = 1,
        allow_retransmission: bool = True,
    ) -> None:
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
        self._modulus = 1 << (vcf_count_length * 8)
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

    def tick(self) -> None:
        if self.higher_interface.buffer_release.is_set():
            # E10 Buffer release signal
            if self.state != Farm1.FarmState.OPEN:
                self.wait = False
                if self.state != Farm1.FarmState.LOCKOUT:
                    self.state = Farm1.FarmState.OPEN
            self.higher_interface.buffer_release.clear()
        try:
            notif = self.lower_interface.signal.pop()
        except IndexError:
            return
        if isinstance(notif, Farm1.ValidFrameArrivedIndication):
            logger.debug(f"Received ValidFrameArrived, {notif.gvcid}")
            frame = self.lower_interface.buffer.pop()
            self._process_frame(frame)
        else:
            raise TypeError(f"Unknown Farm1 signal indication type {type(notif)}")

    def is_in_positive_window(self, ns: int) -> bool:
        """Check if the given sequence number is in the positive window, and does **not** contain
        the expected Frame Sequence Number.

        If it is desired to check if it contains the Frame Sequence Number,
        check N(S) = V(R) directly::

            if self.receiver_frame_sequence_number == ns:
                print("The window contains this frame's sequence number")

        Parameters
        ----------
        ns
            The Transfer Frame's sequence number, N(S)

        Returns
        -------
        bool
            True if N(S) is in the positive window, False otherwise
        """

        return (
            0
            < (ns - self.receiver_frame_sequence_number) % self._modulus
            < self.positive_window_width
        )

    def is_in_negative_window(self, ns: int) -> bool:
        return (
            self.receiver_frame_sequence_number - ns
        ) % self._modulus <= self.negative_window_width

    def is_outside_window(self, ns: int) -> bool:
        return not self.is_in_positive_window(ns) and not self.is_in_negative_window(ns)

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
                self.higher_interface.buffer.append(frame, force=True)
                gvcid = Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                self.higher_interface.signal.append(self.FduArrivedIndication(gvcid), force=True)
                self.b_counter = (self.b_counter + 1) % 4
            else:
                # Type-BC, check commands
                data = frame.tfdf.tfdz
                directive = data[0]
                if directive == 0x00:
                    logger.debug("Received Unlock directive (E7)")
                    self.b_counter = (self.b_counter + 1) % 4
                    self.retransmit = False
                    if self.state == Farm1.FarmState.WAIT:
                        self.wait = False
                    if self.state == Farm1.FarmState.LOCKOUT:
                        self.wait = False
                        self.lockout = False
                    self.state = Farm1.FarmState.OPEN
                elif directive == 0x82 and data[1] == 0:
                    logger.debug(f"Received Set V(R) directive (E8), value={data[2]}")
                    # E8 valid Set V(R)
                    self.b_counter = (self.b_counter + 1) % 4
                    if self.state == Farm1.FarmState.OPEN:
                        self.retransmit = False
                        self.receiver_frame_sequence_number = data[2]
                    elif self.state == Farm1.FarmState.WAIT:
                        self.retransmit = False
                        self.wait = False
                        self.receiver_frame_sequence_number = data[2]
                        self.state = Farm1.FarmState.OPEN
                else:
                    logger.error("Invalid Type-BC directive. Discarding frame")
                    return False
        elif frame.header.bypass_seq_ctrl_flag == BypassSequenceControlFlag.SEQ_CTRLD_QOS:
            if frame.header.prot_ctrl_cmd_flag != ProtocolCommandFlag.USER_DATA:
                logger.error("Discarding frame (E9): invalid 'Type-AC' frame")
                return False
            ns: int = frame.header.vcf_count
            if ns == self.receiver_frame_sequence_number:
                if not self.higher_interface.buffer.appendleft(frame):
                    # E2 No buffer is available
                    self.retransmit = True
                    self.wait = True
                    return False
                else:
                    # E1 buffer is available
                    gvcid = Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                    if not self.higher_interface.signal.appendleft(
                        self.FduArrivedIndication(gvcid)
                    ):
                        logger.error("Unable to append Arrived Indication")
                    if self.state == Farm1.FarmState.OPEN:
                        self.receiver_frame_sequence_number = (
                            self.receiver_frame_sequence_number + 1
                        ) % self._modulus
                        self.retransmit = False
                    elif self.state == Farm1.FarmState.WAIT:
                        raise Exception(
                            "Invalid state WAIT for E1: Type-AD received despite Wait_Flag ON"
                        )
                    elif self.state == Farm1.FarmState.LOCKOUT:
                        logger.warning("Discarding frame (E1,S3)")
                        return False
            elif self.is_in_positive_window(ns):
                # E3 (second case): in the positive window, seq num is incorrect
                logger.warning(f"Discarding frame (E3,{self.state})")
                if self.state == Farm1.FarmState.OPEN:
                    self.retransmit = True
                return False
            elif self.is_in_negative_window(ns):
                # E4 (third case): in negative window. discard, no other actions.
                logger.warning("Discarding frame (E4)")
                return False
            else:
                # E5 outside of window
                logger.warning("Discarding frame (E5)")
                if self.state != Farm1.FarmState.LOCKOUT:
                    self.lockout = True
                    self.state = Farm1.FarmState.LOCKOUT
                return False
        return True
