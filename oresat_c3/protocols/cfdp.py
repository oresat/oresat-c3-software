"""This module contains bugfixes to cfdp-py implementations.

Most or all of these changes should eventually be submitted upstream.
"""

import time
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread

from cfdppy import CfdpState, PacketDestination, get_packet_destination
from cfdppy.exceptions import (
    InvalidDestinationId,
    NoRemoteEntityConfigFound,
    SourceFileDoesNotExist,
)
from cfdppy.handler.dest import CompletionDisposition, DestHandler
from cfdppy.handler.source import SourceHandler
from cfdppy.mib import (
    CheckTimerProvider,
    DefaultFaultHandlerBase,
    EntityType,
    IndicationConfig,
    LocalEntityConfig,
    RemoteEntityConfig,
    RemoteEntityConfigTable,
)
from cfdppy.request import PutRequest
from cfdppy.user import (
    CfdpUserBase,
    FileSegmentRecvdParams,
    MetadataRecvParams,
    TransactionFinishedParams,
    TransactionParams,
)
from olaf import logger
from spacepackets.cfdp import (
    ChecksumType,
    ConditionCode,
    FaultHandlerCode,
    PduHolder,
    TransmissionMode,
)
from spacepackets.cfdp.defs import DeliveryCode, FileStatus, TransactionId
from spacepackets.cfdp.pdu import AbstractFileDirectiveBase, EofPdu, FileDataPdu
from spacepackets.cfdp.pdu.file_data import FileDataParams
from spacepackets.cfdp.tlv import (
    DirectoryListingResponse,
    DirectoryOperationMessageType,
    MessageToUserTlv,
    OriginatingTransactionId,
    ProxyMessageType,
    ProxyPutResponse,
    ProxyPutResponseParams,
    ReservedCfdpMessage,
)
from spacepackets.util import ByteFieldU8


class VfsSourceHandler(SourceHandler):
    """A SourceHandler but modified to always and only use Filestore operations"""

    def _prepare_file_params(self):
        """Fixes the parent implementation not using vfs operations for file ops

        in particular file_exists() and stat()
        """
        assert self._put_req is not None
        if self._put_req.metadata_only:
            self._params.fp.metadata_only = True
            self._params.fp.no_eof = True
        else:
            assert self._put_req.source_file is not None
            if not self.user.vfs.file_exists(self._put_req.source_file):
                raise SourceFileDoesNotExist(self._put_req.source_file)
            file_size = self.user.vfs.file_size(self._put_req.source_file)
            if file_size == 0:
                self._params.fp.metadata_only = True
            else:
                self._params.fp.file_size = file_size

    def _prepare_file_data_pdu(self, offset: int, read_len: int):
        """Fixes the parent not using vfs operations

        They opened source_file manually and then used read_from_open_file(), but read_data()
        will do all that for you but properly.
        """
        assert self._put_req is not None
        assert self._put_req.source_file is not None
        file_data = self.user.vfs.read_data(self._put_req.source_file, offset, read_len)
        fd_params = FileDataParams(file_data=file_data, offset=offset, segment_metadata=None)
        file_data_pdu = FileDataPdu(pdu_conf=self._params.pdu_conf, params=fd_params)
        self._add_packet_to_be_sent(file_data_pdu)


class FixedDestHandler(DestHandler):
    """Fixes to varius methods to prevent it from stalling the satellite"""

    def _handle_positive_ack_procedures(self):
        """Positive ACK procedures according to chapter 4.7.1 of the CFDP standard.
        Returns False if the FSM should be called again."""
        assert self._params.positive_ack_params.ack_timer is not None
        assert self._params.remote_cfg is not None
        if self._params.positive_ack_params.ack_timer.timed_out():
            if (
                self._params.positive_ack_params.ack_counter + 1
                >= self._params.remote_cfg.positive_ack_timer_expiration_limit
            ):
                self._declare_fault(ConditionCode.POSITIVE_ACK_LIMIT_REACHED)
                # This is a bit of a hack: We want the transfer completion and the corresponding
                # re-send of the Finished PDU to happen in the same FSM cycle. However, the call
                # order in the FSM prevents this from happening, so we just call the state machine
                # again manually.
                if self._params.completion_disposition == CompletionDisposition.CANCELED:
                    return self.state_machine()
            # The parent version of this method didn't have the else. Because otherwise it'd get
            # stuck in an infinite loop we set POSITIVE_ACK_LIMIT_REACHED to ABANDON_... instead of
            # ..._CANCELLATION. ABANDON_... will reset self._params, meaning we cant rely on
            # completion_disposition so it was then spuriously generating the below finished_pdu().
            # Also because ._params was empty it was generating a malformed PDU that would throw
            # an exception on pack().
            else:
                self._params.positive_ack_params.ack_timer.reset()
                self._params.positive_ack_params.ack_counter += 1
                self._prepare_finished_pdu()
        return None

    def _handle_eof_pdu(self, eof_pdu: EofPdu):
        """There's a bug in spacepackets EofPdu.unpack() where condition_code doesn't get >> 4

        It should because condition_code is < 16 and it eventually gets passed to AckPdu, where
        it gets packed, and then pack() fails because it's trying to pack a value 256.

        It would be very difficult to override EofPdu directly because it gets used everywhere and
        we don't have control over where. This is the next best thing, _handle_eof_pdu is where
        the pdu gets used, so we can fix up the value before it spreads.
        """
        eof_pdu.condition_code >>= 4
        return super()._handle_eof_pdu(eof_pdu)

    def _handle_eof_without_previous_metadata(self, eof_pdu: EofPdu):
        """Same issue as _handle_eof_pdu"""
        eof_pdu.condition_code >>= 4
        return super()._handle_eof_without_previous_metadata(eof_pdu)


class CfdpUser(CfdpUserBase):
    def __init__(self, base_str: str, put_req_queue: SimpleQueue):
        self.base_str = base_str
        self.put_req_queue = put_req_queue
        # This is a dictionary where the key is the current transaction ID for a transaction which
        # was triggered by a proxy request with an originating ID.
        self.active_proxy_put_reqs: dict[TransactionId, TransactionId] = {}
        super().__init__()

    def transaction_indication(
        self,
        transaction_indication_params: TransactionParams,
    ) -> None:
        """This indication is used to report the transaction ID to the CFDP user"""
        logger.info(
            f"{self.base_str}: Transaction.indication for"
            f" {transaction_indication_params.transaction_id}"
        )
        if transaction_indication_params.originating_transaction_id is not None:
            logger.info(
                f"Originating Transaction ID:"
                f" {transaction_indication_params.originating_transaction_id}"
            )
            self.active_proxy_put_reqs.update(
                {
                    transaction_indication_params.transaction_id: transaction_indication_params.originating_transaction_id  # noqa: E501
                }
            )

    def eof_sent_indication(self, transaction_id: TransactionId) -> None:
        logger.info(f"{self.base_str}: EOF-Sent.indication for {transaction_id}")

    def transaction_finished_indication(self, params: TransactionFinishedParams) -> None:
        logger.info(
            f"{self.base_str}: Transaction-Finished.indication for {params.transaction_id}."
        )
        logger.info(f"Condition Code: {params.finished_params.condition_code!r}")
        logger.info(f"Delivery Code: {params.finished_params.delivery_code!r}")
        logger.info(f"File Status: {params.finished_params.file_status!r}")
        if params.transaction_id in self.active_proxy_put_reqs:
            proxy_put_response = ProxyPutResponse(
                ProxyPutResponseParams.from_finished_params(params.finished_params)
            ).to_generic_msg_to_user_tlv()
            originating_id = self.active_proxy_put_reqs.get(params.transaction_id)
            assert originating_id is not None
            put_req = PutRequest(
                destination_id=originating_id.source_id,
                source_file=None,
                dest_file=None,
                trans_mode=None,
                closure_requested=None,
                msgs_to_user=[
                    proxy_put_response,
                    OriginatingTransactionId(originating_id).to_generic_msg_to_user_tlv(),
                ],
            )
            logger.info(
                f"Requesting Proxy Put Response concluding Proxy Put originating from "
                f"{originating_id}"
            )
            self.put_req_queue.put(put_req)
            self.active_proxy_put_reqs.pop(params.transaction_id)

    def metadata_recv_indication(self, params: MetadataRecvParams) -> None:
        logger.info(f"{self.base_str}: Metadata-Recv.indication for {params.transaction_id}.")
        if params.msgs_to_user is not None:
            self._handle_msgs_to_user(params.transaction_id, params.msgs_to_user)

    def _handle_msgs_to_user(
        self, transaction_id: TransactionId, msgs_to_user: list[MessageToUserTlv]
    ) -> None:
        for msg_to_user in msgs_to_user:
            if msg_to_user.is_reserved_cfdp_message():
                reserved_msg_tlv = msg_to_user.to_reserved_msg_tlv()
                assert reserved_msg_tlv is not None
                self._handle_reserved_cfdp_message(transaction_id, reserved_msg_tlv)
            else:
                logger.info(f"Received custom message to user: {msg_to_user}")

    def _handle_reserved_cfdp_message(
        self, transaction_id: TransactionId, reserved_cfdp_msg: ReservedCfdpMessage
    ) -> None:
        if reserved_cfdp_msg.is_cfdp_proxy_operation():
            self._handle_cfdp_proxy_operation(transaction_id, reserved_cfdp_msg)
        elif reserved_cfdp_msg.is_originating_transaction_id():
            logger.info(
                f"Received originating transaction ID: "
                f"{reserved_cfdp_msg.get_originating_transaction_id()}"
            )

    def _handle_cfdp_proxy_operation(
        self, transaction_id: TransactionId, reserved_cfdp_msg: ReservedCfdpMessage
    ) -> None:
        if reserved_cfdp_msg.get_cfdp_proxy_message_type() == ProxyMessageType.PUT_REQUEST:
            put_req_params = reserved_cfdp_msg.get_proxy_put_request_params()
            logger.info(f"Received Proxy Put Request: {put_req_params}")
            assert put_req_params is not None
            put_req = PutRequest(
                destination_id=put_req_params.dest_entity_id,
                source_file=Path(put_req_params.source_file_as_path),
                dest_file=Path(put_req_params.dest_file_as_path), # Don't really understand why this needs a path. TODO: understand and fix.
                trans_mode=None,
                closure_requested=None,
                msgs_to_user=[
                    OriginatingTransactionId(transaction_id).to_generic_msg_to_user_tlv()
                ],
            )
            self.put_req_queue.put(put_req)
        elif reserved_cfdp_msg.get_cfdp_proxy_message_type() == ProxyMessageType.PUT_RESPONSE:
            put_response_params = reserved_cfdp_msg.get_proxy_put_response_params()
            logger.info(f"Received Proxy Put Response: {put_response_params}")

    def file_segment_recv_indication(self, params: FileSegmentRecvdParams) -> None:
        logger.info(f"{self.base_str}: File-Segment-Recv.indication for {params.transaction_id}.")

    def report_indication(
        self,
        transaction_id: TransactionId,
        status_report: Any,  # noqa ANN401
    ) -> None:
        # TODO: p.28 of the CFDP standard specifies what information the status report parameter
        #       could contain. I think it would be better to not hardcode the type of the status
        #       report here, but something like Union[any, CfdpStatusReport] with CfdpStatusReport
        #       being an implementation which supports all three information suggestions would be
        #       nice
        pass

    def suspended_indication(self, transaction_id: TransactionId, cond_code: ConditionCode) -> None:
        logger.info(
            f"{self.base_str}: Suspended.indication for {transaction_id} |"
            f" Condition Code: {cond_code}"
        )

    def resumed_indication(self, transaction_id: TransactionId, progress: int) -> None:
        logger.info(
            f"{self.base_str}: Resumed.indication for {transaction_id} | Progress: {progress} bytes"
        )

    def fault_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ) -> None:
        logger.info(
            f"{self.base_str}: Fault.indication for {transaction_id} |"
            f" Condition Code: {cond_code} | "
            f"Progress: {progress} bytes"
        )

    def abandoned_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ) -> None:
        logger.info(
            f"{self.base_str}: Abandoned.indication for {transaction_id} |"
            f" Condition Code: {cond_code} |"
            f" Progress: {progress} bytes"
        )

    def eof_recv_indication(self, transaction_id: TransactionId) -> None:
        logger.info(f"{self.base_str}: EOF-Recv.indication for {transaction_id}")

# Don't know what this is for yet. TODO: figure that out.
# class CustomCheckTimerProvider(CheckTimerProvider):
#     def provide_check_timer(
#         self,
#         local_entity_id: ByteFieldU8,
#         remote_entity_id: ByteFieldU8,
#         entity_type: EntityType,
#     ) -> Countdown:
#         return Countdown(timedelta(seconds=5.0))


class SourceEntityHandler(Thread):
    def __init__(
        self,
        source_handler: SourceHandler,
        put_req_queue: SimpleQueue,
        source_entity_queue: SimpleQueue,
        tm_queue: SimpleQueue,
        stop_signal: Event,
    ):
        super().__init__()
        self.source_handler = source_handler
        self.put_req_queue = put_req_queue
        self.source_entity_queue = source_entity_queue
        self.tm_queue = tm_queue
        self.stop_signal = stop_signal

    def _idle_handling(self) -> bool:
        try:
            put_req: PutRequest = self.put_req_queue.get(False)
            logger.info(f"Handling Put Request: {put_req}")
            if put_req.destination_id not in [LOCAL_ENTITY_ID, REMOTE_ENTITY_ID]:
                logger.warning(
                    f"can only handle put requests target towards {REMOTE_ENTITY_ID} or "
                    f"{LOCAL_ENTITY_ID}" # These were global variables. TODO: fix
                )

            else:
                try:
                    self.source_handler.put_request(put_req)
                    return True
                except SourceFileDoesNotExist as e:
                    logger.warning(
                        f"can not handle put request, source file {e.file} does not exist"
                    )
        except Empty:
            pass
        return False

    def _busy_handling(self) -> bool | None:
        # We are getting the packets from a Queue here, they could for example also be polled
        # from a network.
        packet_received = False
        packet = None
        try:
            # We are getting the packets from a Queue here, they could for example also be polled
            # from a network.
            packet = self.source_entity_queue.get(False)
            packet_received = True
        except Empty:
            pass
        try:
            packet_sent = self._call_source_state_machine(packet)
            # If there is no work to do, put the thread to sleep.
            if not packet_received and not packet_sent:
                return False
        except SourceFileDoesNotExist:
            logger.warning("Source file does not exist")
            self.source_handler.reset()

    def _call_source_state_machine(self, packet: AbstractFileDirectiveBase | None) -> bool:
        """Returns whether a packet was sent."""

        if packet is not None:
            logger.debug(f"=Inserting {packet}")
        try:
            fsm_result = self.source_handler.state_machine(packet)
        except InvalidDestinationId as e:
            logger.warning(
                f"invalid destination ID {e.found_dest_id} on packet {packet}, expected "
                f"{e.expected_dest_id}"
            )
            fsm_result = self.source_handler.state_machine(None)
        packet_sent = False
        if fsm_result.states.num_packets_ready > 0:
            while fsm_result.states.num_packets_ready > 0:
                next_pdu_wrapper = self.source_handler.get_next_packet()
                assert next_pdu_wrapper is not None
                if self.verbose_level >= 1:
                    logger.debug(f"Sending packet {next_pdu_wrapper.pdu}")
                # Send all packets which need to be sent.
                self.tm_queue.put(next_pdu_wrapper.pack())
                packet_sent = True
        return packet_sent

    def run(self) -> None:
        logger.info("Starting Source Entity Handler")
        while True:
            if self.stop_signal.is_set():
                break
            if self.source_handler.state == CfdpState.IDLE and not self._idle_handling():
                time.sleep(0.2)
                continue
            if self.source_handler.state == CfdpState.BUSY and not self._busy_handling():
                time.sleep(0.2)


class DestEntityHandler(Thread):
    def __init__(
        self,
        dest_handler: DestHandler,
        dest_entity_queue: SimpleQueue,
        tm_queue: SimpleQueue,
        stop_signal: Event,
    ):
        super().__init__()
        self.dest_handler = dest_handler
        self.dest_entity_queue = dest_entity_queue
        self.tm_queue = tm_queue
        self.stop_signal = stop_signal

    def run(self) -> None:
        logger.info(f"Starting Dest Entity Handler. Local ID {self.dest_handler.cfg.local_entity_id}")
        while True:
            packet_received = False
            packet = None
            if self.stop_signal.is_set():
                break
            try:
                packet = self.dest_entity_queue.get(False)
                packet_received = True
            except Empty:
                pass
            if packet is not None:
                logger.debug(f"Inserting {packet}")
            fsm_result = self.dest_handler.state_machine(packet)
            packet_sent = False
            if fsm_result.states.num_packets_ready > 0:
                while fsm_result.states.num_packets_ready > 0:
                    next_pdu_wrapper = self.dest_handler.get_next_packet()
                    assert next_pdu_wrapper is not None
                    if self.verbose_level >= 1:
                        logger.debug(f"Sending packet {next_pdu_wrapper.pdu}")
                    self.tm_queue.put(next_pdu_wrapper.pack())
                    packet_sent = True
            # If there is no work to do, put the thread to sleep.
            if not packet_received and not packet_sent:
                time.sleep(0.5)

