from common.fsm import StateMachine

from ._fop1_events import FopEvent
from .types import FopState, Alert

_ignore = []

_synch = ["_alert_SYNCH"]
_e1 = ["confirm", "cancel_timer"]
_e1_2 = ["confirm", "release_copy_of_bc_frame", "cancel_timer"]
_e2 = ["remove_acknowledged_frames_from_sent_queue", "cancel_timer", "look_for_fdu"]
_e6 = ["remove_acknowledged_frames_from_sent_queue", "look_for_fdu"]
_e8 = [
    "remove_acknowledged_frames_from_sent_queue",
    "initiate_retransmission",
    "look_for_fdu",
]
_e9 = ["remove_acknowledged_frames_from_sent_queue"]
_e10 = ["initiate_retransmission", "look_for_fdu"]

_transitions: dict[StateMachine.TRANSITION_FROM, StateMachine.TRANSITION_TO] = {
    # S1
    (FopState.ACTIVE, FopEvent.E1): (FopState.ACTIVE, _ignore),
    (FopState.ACTIVE, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.ACTIVE, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.ACTIVE, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.ACTIVE, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.ACTIVE, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.ACTIVE, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S2
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E1): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S3
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E1): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    # S4
    (FopState.INITIALIZING_NO_BC, FopEvent.E1): (FopState.ACTIVE, _e1),
    # S5
    (FopState.INITIALIZING_WITH_BC, FopEvent.E1): (FopState.ACTIVE, _e1_2),
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
