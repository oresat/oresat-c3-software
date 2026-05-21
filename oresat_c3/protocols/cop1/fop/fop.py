import threading
from collections import deque
from typing import Optional

from common.ccsds import ControlWord, Gvcid
from common.fsm import StateMachine
from common.service import CopService
from common.util import logger
from spacepackets.uslp import BypassSequenceControlFlag, ProtocolCommandFlag
from uslp import SPACECRAFT_ID

from ._fop1_events import FopEvent
from .transitions import _transitions
from .types import (
    AbortRequest,
    Alert,
    AsyncNotification,
    AsyncNotificationType,
    FopState,
    SentQueueEntry,
    ServiceType,
    TransferNotification,
    TransferNotificationType,
    TransmitRequestForFrame,
    WaitQueueEntry,
)


class Fop1(CopService):
    """Frame Operation Procedure-1 (FOP-1), CCSDS 323.1-B-2"""

    _transitions = {}

    def __init__(
        self,
        vcid: int,
        k: int = 10,
    ) -> None:
        super().__init__()
        self.state: FopState = FopState.INITIAL
        # TRANSMITTER_FRAME_SEQUENCE_NUMBER, V(S)
        self.v_s: int = 0
        self._wait_queue: Optional[WaitQueueEntry] = None
        self._sent_queue: deque[SentQueueEntry] = deque()
        # True == Ready and False == Not_Ready
        self.ad_out: bool = False
        self.bd_out: bool = False
        self.bc_out: bool = False
        # Expected_Acknowledgement_Frame_Sequence_Number
        self.nn_r: int = 0
        self.timer_initial_value: int = 0
        self.transmission_limit: int = 1  # TODO: might be good to have in OD
        self.transmission_count: int = 0
        if k < 1 or k >= 256:
            raise ValueError("k must be between 1 and 256")
        self.sliding_window_width: int = k  # 'K'
        self.timeout_type: int
        self.suspend_state: int

        self._timer = None
        self._request_id: int = 0
        self._gvcid: Gvcid = Gvcid(0b1100, SPACECRAFT_ID, vcid)

        self._fsm = StateMachine[FopState, FopEvent](FopState.INITIAL)
        for tr_from, tr_to in _transitions.items():
            self._fsm.add_transition(tr_from, tr_to)

    def on_clcw_arrived(self, clcw: ControlWord) -> None:
        if not self._validate_clcw(clcw):
            self.on_event(FopEvent.E15)
        if clcw.lockout:
            self.on_event(FopEvent.E14)
        else:
            if clcw.report_value == self.v_s:
                # valid N(R) and all outstanding Type-AD acked
                if clcw.retransmit:
                    self.on_event(FopEvent.E4)
                else:
                    if clcw.wait:
                        self.on_event(FopEvent.E3)
                    else:
                        if clcw.report_value == self.nn_r:
                            # no new frames acked
                            self.on_event(FopEvent.E1)
                        else:
                            # some new frames acked
                            self.on_event(FopEvent.E2)
            elif self.v_s > clcw.report_value >= self.nn_r:
                # valid N(R) and some outstanding AD not yet acked
                if clcw.retransmit:
                    if self.transmission_limit == 1:
                        if clcw.report_value == self.nn_r:
                            self.on_event(FopEvent.E102)
                        else:
                            self.on_event(FopEvent.E101)
                    elif self.transmission_limit > 1:
                        if clcw.report_value == self.nn_r:
                            if self.transmission_count < self.transmission_limit:
                                if clcw.wait:
                                    self.on_event(FopEvent.E11_B)
                                else:
                                    self.on_event(FopEvent.E10_B)
                            else:
                                if clcw.wait:
                                    self.on_event(FopEvent.E103)
                                else:
                                    self.on_event(FopEvent.E12_B)
                        else:
                            if clcw.wait:
                                self.on_event(FopEvent.E8_B)
                            else:
                                self.on_event(FopEvent.E9_B)
                    else:
                        logger.error("Transmission_Limit < 1")
                        self.transmission_limit = 1
            else:
                # invalid N(R)
                self.on_event(FopEvent.E13)

    def _validate_clcw(self, clcw: ControlWord) -> bool:
        return clcw.cop_in_effect == 0b01 and clcw.vcid == self._gvcid.vcid

    def on_event(self, event: FopEvent) -> None:
        logger.debug(f"Event received: {event}")
        self._fsm.process_event(event)

    def start_timer(self) -> None:
        if self._timer is not None:
            self.cancel_timer()
        self._timer = threading.Timer(self.timer_initial_value, self._on_timer_expired)
        self._timer.start()

    def cancel_timer(self) -> None:
        self._timer.cancel()

    def _on_timer_expired(self) -> None:
        pass

    def alert(self, alert_type: Alert) -> None:
        logger.debug(f"Alert received: {alert_type}")
        self.higher_interface.signal.appendleft(
            AsyncNotification(self._gvcid, AsyncNotificationType.ALERT, alert_type)
        )

    def remove_acknowledged_frames_from_sent_queue(self) -> None:
        entries = list(self._sent_queue)
        self._sent_queue.clear()
        for entry in entries:
            notif = TransferNotification(
                entry.request_id, entry.gvcid, TransferNotificationType.POSITIVE_CONFIRM
            )
            self.higher_interface.signal.appendleft(notif)
            self.nn_r = (self.nn_r + 1) & 0xFF
        self.transmission_count = 1

    def initiate_retransmission(self) -> None:
        self.lower_interface.signal.appendleft(AbortRequest(self._gvcid))
        self.transmission_count += 1
        self.start_timer()
        for entry in self._sent_queue:
            entry.to_be_retransmitted = True

    def look_for_fdu(self) -> None:
        if self.ad_out:
            result = next((entry for entry in self._sent_queue if entry.to_be_retransmitted), None)
            if result is not None:
                self.ad_out = False
                self.lower_interface.signal.appendleft(
                    TransmitRequestForFrame(
                        result.gvcid,
                        BypassSequenceControlFlag.SEQ_CTRLD_QOS,
                        ProtocolCommandFlag.USER_DATA,
                        result.n_s,
                        result.tfdf,
                    )
                )
                result.to_be_retransmitted = False
            elif self.v_s < self.nn_r + self.sliding_window_width:
                if self._wait_queue is not None and self._wait_queue.service_type == ServiceType.AD:
                    waiting_fdu = self._wait_queue
                    self._wait_queue = None
                    self.higher_interface.signal.appendleft(
                        TransferNotification(
                            waiting_fdu.request_id, TransferNotificationType.ACCEPT
                        )
                    )
                    self.transmit_type_ad_frame(waiting_fdu)

    def transmit_type_ad_frame(self, entry: WaitQueueEntry) -> None:
        n_s = self.v_s
        sent_entry = SentQueueEntry(entry.request_id, entry.gvcid, entry.fdu, n_s)
        self.v_s = (self.v_s + 1) & 0xFF
        if len(self._sent_queue) == 0:
            self.transmission_count = 1
        self._sent_queue.append(sent_entry)
        self.start_timer()
        self.ad_out = False
        self.lower_interface.signal.appendleft(
            TransmitRequestForFrame(
                BypassSequenceControlFlag.SEQ_CTRLD_QOS,
                ProtocolCommandFlag.USER_DATA,
                n_s,
            )
        )
