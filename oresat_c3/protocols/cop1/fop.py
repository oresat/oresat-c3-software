from enum import unique
from typing import Optional

from spacepackets.uslp import TransferFrame

from .common import CopEvent, CopService, CopState, StateMachine


@unique
class FopState(CopState):
    """The state of FOP-1

    CCSDS 232.1-B-2 § 5.1.2
    """

    ACTIVE = 1
    RETRANSMIT_NO_WAIT = 2
    RETRANSMIT_WITH_WAIT = 3
    INITIALIZING_NO_BC = 4
    INITIALIZING_WITH_BC = 5
    INITIAL = 6


class FopEvent(CopEvent):
    pass


# redefinition for type checker parsing
FopEvent = CopEvent("FopEvent", {f"E{i}" for i in range(1, 47)})


class Fop1(CopService):
    """Frame Operation Procedure-1 (FOP-1), CCSDS 323.1-B-2"""

    def __init__(
        self,
        k: int = 10,
    ) -> None:
        super().__init__()
        self.state: FopState = FopState.INITIAL
        # TRANSMITTER_FRAME_SEQUENCE_NUMBER, V(S)
        self.v_s: int = 0
        self.wait_queue: Optional[TransferFrame] = None
        self.send_queue: Optional[TransferFrame] = None
        self.to_be_retransmitted: bool
        self.ad_out: bool
        self.bd_out: bool
        self.bc_out: bool
        # Expected_Acknowledgement_Frame_Sequence_Number
        self.nn_r: int = 0
        self.timer_initial_value: int = 0
        self.transmission_limit: int
        self.transmission_count: int
        if k < 1 or k >= 256:
            raise ValueError("k must be between 1 and 256")
        self.sliding_window_width: int  # 'K'
        self.timeout_type: int
        self.suspend_state: int

        self._fsm = StateMachine[FopState, FopEvent](FopState.INITIAL)
