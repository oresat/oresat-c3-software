from . import StateMachine
from ._fop1_events import FopEvent
from .fop import Fop1, FopState

_ignore = []

_e2 = [Fop1.remove_acknowledged_frames_from_sent_queue, Fop1.cancel_timer, Fop1.look_for_fdu]
_e6 = [Fop1.remove_acknowledged_frames_from_sent_queue, Fop1.look_for_fdu]
_e8 = [
    Fop1.remove_acknowledged_frames_from_sent_queue,
    Fop1.initiate_retransmission,
    Fop1.look_for_fdu,
]
_e9 = [Fop1.remove_acknowledged_frames_from_sent_queue]
_e10 = [Fop1.initiate_retransmission, Fop1.look_for_fdu]

_transitions: dict[StateMachine.TRANSITION_FROM, StateMachine.TRANSITION_TO] = {
    # S1
    (FopState.ACTIVE, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.ACTIVE, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.ACTIVE, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.ACTIVE, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.ACTIVE, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.ACTIVE, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S2
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S3
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S6
    (FopState.INITIAL, FopEvent.E1): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E2): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E3): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E4): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E5): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E6_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E7_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E8_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E9_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E10_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E11_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E12_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E103): (FopState.INITIAL, _ignore),
}
