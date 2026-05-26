from common.fsm import StateMachine

from ._fop1_events import FopEvent
from .types import FopState

_ignore = []
_reject_fdu = ["reject_fdu"]
_reject_directive = ["reject_directive"]
_resume = ["accept_directive", "resume", "confirm_directive"]

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
_e23 = ["accept_directive", "initialize", "confirm_directive"]
_e24 = ["accept_directive", "initialize", "start_timer"]
_e25 = ["accept_directive", "initialize", "transmit_unlock_bc_frame"]
_e29 = ["accept_directive", "_alert_TERM", "confirm_directive"]
_e36 = ["accept_directive", "set_k", "confirm_directive"]
_e37 = ["accept_directive", "set_t1_initial", "confirm_directive"]
_e38 = ["accept_directive", "set_transmission_limit", "confirm_directive"]
_e39 = ["accept_directive", "set_tt", "confirm_directive"]

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
    (FopState.ACTIVE, FopEvent.E23): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E24): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E25_B): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E26): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E27_B): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E28): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E29): (FopState.INITIAL, _e29),
    (FopState.ACTIVE, FopEvent.E30): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E35_B): (FopState.ACTIVE, _reject_directive),
    (FopState.ACTIVE, FopEvent.E36): (FopState.ACTIVE, _e36),
    (FopState.ACTIVE, FopEvent.E37): (FopState.ACTIVE, _e37),
    (FopState.ACTIVE, FopEvent.E38): (FopState.ACTIVE, _e38),
    (FopState.ACTIVE, FopEvent.E39): (FopState.ACTIVE, _e39),
    (FopState.ACTIVE, FopEvent.E40): (FopState.ACTIVE, _reject_directive),
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
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E23): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E24): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E25_B): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E26): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E27_B): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E28): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E29): (FopState.INITIAL, _e29),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E30): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E35_B): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E36): (FopState.RETRANSMIT_NO_WAIT, _e36),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E37): (FopState.RETRANSMIT_NO_WAIT, _e37),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E38): (FopState.RETRANSMIT_NO_WAIT, _e38),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E39): (FopState.RETRANSMIT_NO_WAIT, _e39),
    (FopState.RETRANSMIT_NO_WAIT, FopEvent.E40): (FopState.RETRANSMIT_NO_WAIT, _reject_directive),
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
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E23): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E24): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E25_B): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E26): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E27_B): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E28): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E29): (FopState.INITIAL, _e29),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E30): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E35_B): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E36): (FopState.RETRANSMIT_WITH_WAIT, _e36),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E37): (FopState.RETRANSMIT_WITH_WAIT, _e37),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E38): (FopState.RETRANSMIT_WITH_WAIT, _e38),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E39): (FopState.RETRANSMIT_WITH_WAIT, _e39),
    (FopState.RETRANSMIT_WITH_WAIT, FopEvent.E40): (
        FopState.RETRANSMIT_WITH_WAIT,
        _reject_directive,
    ),
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
    (FopState.INITIALIZING_NO_BC, FopEvent.E23): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E24): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E25_B): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E26): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E27_B): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E28): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E29): (FopState.INITIAL, _e29),
    (FopState.INITIALIZING_NO_BC, FopEvent.E30): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E35_B): (FopState.INITIALIZING_NO_BC, _reject_directive),
    (FopState.INITIALIZING_NO_BC, FopEvent.E36): (FopState.INITIALIZING_NO_BC, _e36),
    (FopState.INITIALIZING_NO_BC, FopEvent.E37): (FopState.INITIALIZING_NO_BC, _e37),
    (FopState.INITIALIZING_NO_BC, FopEvent.E38): (FopState.INITIALIZING_NO_BC, _e38),
    (FopState.INITIALIZING_NO_BC, FopEvent.E39): (FopState.INITIALIZING_NO_BC, _e39),
    (FopState.INITIALIZING_NO_BC, FopEvent.E40): (FopState.INITIALIZING_NO_BC, _reject_directive),
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
    (FopState.INITIALIZING_WITH_BC, FopEvent.E23): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E24): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E25_B): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E26): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E27_B): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E28): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E29): (FopState.INITIAL, _e29),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E30): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E35_B): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E36): (FopState.INITIALIZING_WITH_BC, _e36),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E37): (FopState.INITIALIZING_WITH_BC, _e37),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E38): (FopState.INITIALIZING_WITH_BC, _e38),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E39): (FopState.INITIALIZING_WITH_BC, _e39),
    (FopState.INITIALIZING_WITH_BC, FopEvent.E40): (
        FopState.INITIALIZING_WITH_BC,
        _reject_directive,
    ),
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
    (FopState.INITIAL, FopEvent.E23): (FopState.ACTIVE, _e23),
    (FopState.INITIAL, FopEvent.E24): (FopState.INITIALIZING_NO_BC, _e24),
    (FopState.INITIAL, FopEvent.E25_B): (FopState.INITIALIZING_WITH_BC, _e25),
    (FopState.INITIAL, FopEvent.E26): (FopState.INITIAL, _reject_directive),
    (FopState.INITIAL, FopEvent.E27_B): (
        FopState.INITIALIZING_WITH_BC,
        ["accept_directive", "initialize", "set_pending_v_r", "transmit_set_v_r_bc_frame"],
    ),
    (FopState.INITIAL, FopEvent.E28): (FopState.INITIAL, _reject_directive),
    (FopState.INITIAL, FopEvent.E29): (FopState.INITIAL, ["accept_directive", "confirm_directive"]),
    (FopState.INITIAL, FopEvent.E30): (FopState.INITIAL, _reject_directive),
    (FopState.INITIAL, FopEvent.E31_B): (FopState.ACTIVE, _resume),
    (FopState.INITIAL, FopEvent.E32_B): (FopState.RETRANSMIT_NO_WAIT, _resume),
    (FopState.INITIAL, FopEvent.E33_B): (FopState.RETRANSMIT_WITH_WAIT, _resume),
    (FopState.INITIAL, FopEvent.E34_B): (FopState.INITIALIZING_NO_BC, _resume),
    (FopState.INITIAL, FopEvent.E35_B): (FopState.INITIAL, ["_gated_set_v_s_"]),
    (FopState.INITIAL, FopEvent.E36): (FopState.INITIAL, _e36),
    (FopState.INITIAL, FopEvent.E37): (FopState.INITIAL, _e37),
    (FopState.INITIAL, FopEvent.E38): (FopState.INITIAL, _e38),
    (FopState.INITIAL, FopEvent.E39): (FopState.INITIAL, _e39),
    (FopState.INITIAL, FopEvent.E40): (FopState.INITIAL, _reject_directive),
}
