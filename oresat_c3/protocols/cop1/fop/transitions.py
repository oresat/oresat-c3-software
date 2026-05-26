from common.fsm import StateMachine

from ._fop1_events import FopEvent
from .types import FopState

_ignore = []
_reject_fdu = ["reject_fdu"]

_synch = ["_alert_SYNCH"]
_nnr = ["_alert_NNR"]
_clcw = ["_alert_CLCW"]
_limit = ["_alert_LIMIT"]
_lockout = ["_alert_LOCKOUT"]
_t1 = ["_alert_T1"]
_suspend = ["suspend"]
_e1 = ["confirm_directive", "cancel_timer"]
_e1_2 = ["confirm_directive", "release_copy_of_bc_frame", "cancel_timer"]
_e2 = ["remove_acknowledged_frames_from_sent_queue", "cancel_timer", "look_for_fdu"]
_e6 = ["remove_acknowledged_frames_from_sent_queue", "look_for_fdu"]
_e101 = ["remove_acknowledged_frames_from_sent_queue", "_alert_LIMIT"]
_e8 = [
    "remove_acknowledged_frames_from_sent_queue",
    "initiate_retransmission",
    "look_for_fdu",
]
_e9 = ["remove_acknowledged_frames_from_sent_queue"]
_e10 = ["initiate_retransmission", "look_for_fdu"]
_e16 = ["initiate_retransmission", "look_for_directive"]
_e19 = ["add_to_wait_queue", "look_for_fdu"]
_e21 = ["accept_fdu", "transmit_type_bd_frame"]

_transitions: dict[StateMachine.TRANSITION_FROM, StateMachine.TRANSITION_TO] = {
    # S1
    (FopState.ACTIVE, FopEvent.E1): (FopState.ACTIVE, _ignore),
    (FopState.ACTIVE, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.ACTIVE, FopEvent.E3): (FopState.INITIAL, _clcw),
    (FopState.ACTIVE, FopEvent.E4): (FopState.INITIAL, _synch),
    (FopState.ACTIVE, FopEvent.E5): (FopState.ACTIVE, _ignore),
    (FopState.ACTIVE, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.ACTIVE, FopEvent.E7_B): (FopState.INITIAL, _clcw),
    (FopState.ACTIVE, FopEvent.E101): (FopState.INITIAL, _e101),
    (FopState.ACTIVE, FopEvent.E102): (FopState.INITIAL, _limit),
    (FopState.ACTIVE, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.ACTIVE, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.ACTIVE, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.ACTIVE, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.ACTIVE, FopEvent.E13): (FopState.INITIAL, _nnr),
    (FopState.ACTIVE, FopEvent.E14): (FopState.INITIAL, _lockout),
    (FopState.ACTIVE, FopEvent.E15): (FopState.INITIAL, _clcw),
    (FopState.ACTIVE, FopEvent.E16_B): (FopState.ACTIVE, _e10),
    (FopState.ACTIVE, FopEvent.E104): (FopState.ACTIVE, _e10),
    (FopState.ACTIVE, FopEvent.E17_B): (FopState.INITIAL, _t1),
    (FopState.ACTIVE, FopEvent.E18_B): (FopState.INITIAL, _suspend),
    (FopState.ACTIVE, FopEvent.E19): (FopState.ACTIVE, _e19),
    (FopState.ACTIVE, FopEvent.E20): (FopState.ACTIVE, _reject_fdu),
    (FopState.ACTIVE, FopEvent.E21_B): (FopState.ACTIVE, _e21),
    (FopState.ACTIVE, FopEvent.E22): (FopState.ACTIVE, _reject_fdu),
    # S2
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E1): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E3): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E4): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E5): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E7_B): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E101): (FopState.INITIAL, _e101),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E102): (FopState.INITIAL, _limit),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E13): (FopState.INITIAL, _nnr),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E14): (FopState.INITIAL, _lockout),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E15): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E16_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E104): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E17_B): (FopState.INITIAL, _t1),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E18_B): (FopState.INITIAL, _suspend),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E19): (FopState.RETRANSMIT_NO_WAIT, _e19),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E20): (FopState.RETRANSMIT_NO_WAIT, _reject_fdu),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E21_B): (FopState.RETRANSMIT_NO_WAIT, _e21),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E22): (FopState.RETRANSMIT_NO_WAIT, _reject_fdu),
    # S3
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E1): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E2): (FopState.ACTIVE, _e2),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E3): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E4): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E5): (FopState.INITIAL, _synch),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E6_B): (FopState.ACTIVE, _e6),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E7_B): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E101): (FopState.INITIAL, _e101),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E102): (FopState.INITIAL, _limit),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E8_B): (FopState.RETRANSMIT_NO_WAIT, _e8),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E9_B): (FopState.RETRANSMIT_WITH_WAIT, _e9),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E10_B): (FopState.RETRANSMIT_NO_WAIT, _e10),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E11_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E12_B): (FopState.RETRANSMIT_NO_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E103): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E13): (FopState.INITIAL, _nnr),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E14): (FopState.INITIAL, _lockout),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E15): (FopState.INITIAL, _clcw),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E16_B): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E104): (FopState.RETRANSMIT_WITH_WAIT, _ignore),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E17_B): (FopState.INITIAL, _t1),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E18_B): (FopState.INITIAL, _suspend),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E19): (
        FopState.RETRANSMIT_WITH_WAIT,
        ["add_to_wait_queue"],
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E20): (FopState.RETRANSMIT_WITH_WAIT, _reject_fdu),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E21_B): (FopState.RETRANSMIT_WITH_WAIT, _e21),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E22): (FopState.RETRANSMIT_WITH_WAIT, _reject_fdu),
    # S4
    (FopState.INITIALIZING_NO_BC, FopEvent.E1): (FopState.ACTIVE, _e1),
    (FopState.INITIALIZING_NO_BC, FopEvent.E3): (FopState.INITIAL, _clcw),
    (FopState.INITIALIZING_NO_BC, FopEvent.E4): (FopState.INITIAL, _synch),
    (FopState.INITIALIZING_NO_BC, FopEvent.E13): (FopState.INITIAL, _nnr),
    (FopState.INITIALIZING_NO_BC, FopEvent.E14): (FopState.INITIAL, _lockout),
    (FopState.INITIALIZING_NO_BC, FopEvent.E15): (FopState.INITIAL, _clcw),
    (FopState.INITIALIZING_NO_BC, FopEvent.E16_B): (FopState.INITIAL, _t1),
    (FopState.INITIALIZING_NO_BC, FopEvent.E104): (FopState.INITIAL, _suspend),
    (FopState.INITIALIZING_NO_BC, FopEvent.E17_B): (FopState.INITIAL, _t1),
    (FopState.INITIALIZING_NO_BC, FopEvent.E18_B): (FopState.INITIAL, _suspend),
    (FopState.INITIALIZING_NO_BC, FopEvent.E19): (FopState.INITIALIZING_NO_BC, _reject_fdu),
    (FopState.INITIALIZING_NO_BC, FopEvent.E20): (FopState.INITIALIZING_NO_BC, _reject_fdu),
    (FopState.INITIALIZING_NO_BC, FopEvent.E21_B): (FopState.INITIALIZING_NO_BC, _e21),
    (FopState.INITIALIZING_NO_BC, FopEvent.E22): (FopState.INITIALIZING_NO_BC, _reject_fdu),
    # S5
    (FopState.INITIALIZING_WITH_BC, FopEvent.E1): (FopState.ACTIVE, _e1_2),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E3): (FopState.INITIALIZING_WITH_BC, _ignore),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E4): (FopState.INITIALIZING_WITH_BC, _ignore),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E13): (FopState.INITIALIZING_WITH_BC, _ignore),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E14): (FopState.INITIALIZING_WITH_BC, _ignore),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E15): (FopState.INITIAL, _clcw),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E16_B): (FopState.INITIALIZING_WITH_BC, _e16),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E16_B): (FopState.INITIALIZING_WITH_BC, _e16),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E17_B): (FopState.INITIAL, _t1),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E18_B): (FopState.INITIAL, _suspend),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E19): (FopState.INITIALIZING_WITH_BC, _reject_fdu),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E20): (FopState.INITIALIZING_WITH_BC, _reject_fdu),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E21_B): (FopState.INITIALIZING_WITH_BC, _e21),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E22): (FopState.INITIALIZING_WITH_BC, _reject_fdu),
    # S6
    (FopState.INITIAL, FopEvent.E1): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E2): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E3): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E4): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E5): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E6_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E7_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E101): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E102): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E8_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E9_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E10_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E11_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E12_B): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E103): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E13): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E14): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E15): (FopState.INITIAL, _ignore),
    (FopState.INITIAL, FopEvent.E19): (FopState.INITIAL, _reject_fdu),
    (FopState.INITIAL, FopEvent.E20): (FopState.INITIAL, _reject_fdu),
    (FopState.INITIAL, FopEvent.E21_B): (FopState.INITIAL, _e21),
    (FopState.INITIAL, FopEvent.E22): (FopState.INITIAL, _reject_fdu),
}
