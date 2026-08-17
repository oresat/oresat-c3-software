"""This module contains bugfixes to cfdp-py implementations.

Most or all of these changes should eventually be submitted upstream.
"""

# FIXME: Lets this file pass py3.9 tests. Remove when tests use 3.12
from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread

from cfdppy import CfdpState
from cfdppy.exceptions import (
    InvalidDestinationId,
    NoRemoteEntityConfigFound,
    PduIgnoredForDest,
    PduIgnoredForSource,
    SourceFileDoesNotExist,
)
from cfdppy.filestore import FilestoreResult
from cfdppy.handler.dest import CompletionDisposition, DestHandler
from cfdppy.handler.dest import TransactionStep as DestTransactionStep
from cfdppy.handler.source import SourceHandler
from cfdppy.handler.source import TransactionStep as SrcTransactionStep
from cfdppy.mib import (
    CheckTimerProvider,
    DefaultFaultHandlerBase,
    EntityType,
    IndicationConfig,
    LocalEntityConfig,
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
    ConditionCode,
    FaultHandlerCode,
    PduHolder,
    TransmissionMode,
)
from spacepackets.cfdp.defs import DeliveryCode, TransactionId
from spacepackets.cfdp.pdu import (
    AbstractFileDirectiveBase,
    DirectiveType,
    EofPdu,
    FileDataPdu,
    MetadataPdu,
)
from spacepackets.cfdp.pdu.file_data import FileDataParams
from spacepackets.cfdp.tlv import (
    DirectoryOperationMessageType,
    MessageToUserTlv,
    OriginatingTransactionId,
    ProxyMessageType,
    ProxyPutResponse,
    ProxyPutResponseParams,
    ReservedCfdpMessage,
    TlvType,
)
from spacepackets.countdown import Countdown
from spacepackets.seqcount import SeqCountProvider
from spacepackets.util import ByteFieldU8

from .cachestore import CacheStore


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

    def _sending_file_data_fsm(self, packet_holder: PduHolder) -> bool:
        """Fixes the parent not sending EOFs for metadata only transactions. CCSDS 720.1-G-4 and
        YAMCS both have proxy put requests sending EOFs, so this brings cfdppy into compliance.
        """
        if (
            self.transmission_mode == TransmissionMode.ACKNOWLEDGED
            and super()._SourceHandler__handle_retransmission(packet_holder)
        ):
            return True
        # No need to send a file data PDU for an empty file
        if (
            not self._params.fp.metadata_only
            and self._params.fp.progress < self._params.fp.file_size
        ):
            self._prepare_progressing_file_data_pdu()
            # Not finished yet. We exit here to allow the user to do flow control.
            return True
        if self._params.fp.empty_file or self._params.fp.metadata_only:
            self._params.cond_code_eof = ConditionCode.NO_ERROR
            self.states.step = SrcTransactionStep.SENDING_EOF
        return False

    def _checksum_calculation(self, size_to_calculate: int) -> bytes:
        if self._params.fp.metadata_only:
            return b'\0' * 4
        return super()._checksum_calculation(size_to_calculate)

    def _transaction_start(self) -> None:
        # seems to be an issue where proxy put responses are expected by the source handler to have
        # a file size. This alters the assert to allow for metadata only PDUs from the source.
        originating_transaction_id = self._check_for_originating_id()
        self._prepare_file_params()
        assert self._params.fp.file_size is not None or self._params.fp.metadata_only
        self._prepare_pdu_conf(self._params.fp.file_size)
        self._get_next_transfer_seq_num()
        self._calculate_max_file_seg_len()
        self._params.transaction_id = TransactionId(
            source_entity_id=self.cfg.local_entity_id,
            transaction_seq_num=self.transaction_seq_num,
        )
        self.user.transaction_indication(
            TransactionParams(self._params.transaction_id, originating_transaction_id)
        )


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

        I've made this shelf stable for when it eventually gets fixed.
        """
        if eof_pdu.condition_code > 15:
            eof_pdu.condition_code >>= 4
        return super()._handle_eof_pdu(eof_pdu)

    def _handle_eof_without_previous_metadata(self, eof_pdu: EofPdu):
        """Same issue as _handle_eof_pdu"""
        if eof_pdu.condition_code > 15:
            eof_pdu.condition_code >>= 4
        return super()._handle_eof_without_previous_metadata(eof_pdu)

    def _handle_waiting_for_finished_ack(self, packet_holder: PduHolder) -> None:
        """
        The dest handler will not resend the EOF ack if it gets lost. The ordreing of the FSM means
        that this can also try to resend when getting the normal EOF, so this does not resend if the
        queue already has something. There is probably a cleaner way to handle this.
        """
        if (
            packet_holder.pdu is not None
            and packet_holder.pdu_directive_type == DirectiveType.EOF_PDU
            and self.states._num_packets_ready == 0
        ):
            self._handle_eof_pdu(packet_holder.pdu)
        super()._handle_waiting_for_finished_ack(packet_holder)

    def _handle_metadata_packet(self, metadata_pdu: MetadataPdu) -> None:
        """Fixes the desthandler ending as soon as a proxy put request Metadata PDU is received."""
        assert self._params.transaction_id is not None
        self._params.checksum_type = metadata_pdu.checksum_type
        self._params.closure_requested = metadata_pdu.closure_requested
        self._params.acked_params.metadata_missing = False
        if metadata_pdu.dest_file_name is None or metadata_pdu.source_file_name is None:
            self._params.fp.metadata_only = True
            self._params.finished_params.delivery_code = DeliveryCode.DATA_COMPLETE
        else:
            self._params.fp.file_name = Path(metadata_pdu.dest_file_name)
        self._params.fp.file_size = metadata_pdu.file_size
        # To be fully standard-compliant or at least allow the flexibility to be standard-compliant
        # in the future, we should require that a remote entity configuration exists for each CFDP
        # sender.
        if self._params.remote_cfg is None:
            logger.warning(
                f"No remote configuration found for remote ID {metadata_pdu.dest_entity_id}"
            )
            raise NoRemoteEntityConfigFound(metadata_pdu.dest_entity_id)
        self.states.step = DestTransactionStep.RECEIVING_FILE_DATA
        if not self._params.fp.metadata_only:
            assert metadata_pdu.source_file_name is not None
            self._init_vfs_handling(Path(metadata_pdu.source_file_name).name)
        msgs_to_user_list: list[MessageToUserTlv] | None = None
        options = metadata_pdu.options_as_tlv()
        if options is not None:
            msgs_to_user_list = []
            for tlv in options:
                if tlv.tlv_type == TlvType.MESSAGE_TO_USER:
                    msgs_to_user_list.append(MessageToUserTlv.from_tlv(tlv))
        file_size_for_indication = (
            None if metadata_pdu.source_file_name is None else metadata_pdu.file_size
        )
        params = MetadataRecvParams(
            transaction_id=self._params.transaction_id,
            file_size=file_size_for_indication,
            source_id=metadata_pdu.source_entity_id,
            dest_file_name=metadata_pdu.dest_file_name,
            source_file_name=metadata_pdu.source_file_name,
            msgs_to_user=msgs_to_user_list,
        )
        self.user.metadata_recv_indication(params)

    def _declare_fault(self, cond: ConditionCode) -> FaultHandlerCode:
        """
        As far as I can tell abandon transaction is never called, so the dest handler endlessly
        tries to cancel transactions without ever actually ending them.
        """
        fh = self.cfg.default_fault_handlers.get_fault_handler(cond)
        transaction_id = self._params.transaction_id
        progress = self._params.fp.progress
        assert transaction_id is not None
        if fh is None:
            raise ValueError(f"invalid condition code {cond!r} for fault declaration")
        if fh == FaultHandlerCode.NOTICE_OF_CANCELLATION:
            if (  # If we've already cancelled, abandon instead
                self._params.completion_disposition == CompletionDisposition.CANCELED
            ):
                fh = FaultHandlerCode.ABANDON_TRANSACTION
                self._abandon_transaction()
            else:
                self._notice_of_cancellation(cond)
        elif fh == FaultHandlerCode.NOTICE_OF_SUSPENSION:
            self._notice_of_suspension()
        elif fh == FaultHandlerCode.ABANDON_TRANSACTION:
            self._abandon_transaction()
        self.cfg.default_fault_handlers.report_fault(transaction_id, cond, progress)
        return fh


class CfdpFaultHandler(DefaultFaultHandlerBase):
    def __init__(self, base_str: str):
        self.base_str = base_str
        super().__init__()

    def notice_of_suspension_cb(
        self, transaction_id: TransactionId, cond: ConditionCode, progress: int
    ) -> None:
        logger.warning(
            f"{self.base_str}: Received Notice of Suspension for transaction {transaction_id!r} "
            f"with condition code {cond!r}. Progress: {progress}"
        )

    def notice_of_cancellation_cb(
        self, transaction_id: TransactionId, cond: ConditionCode, progress: int
    ) -> None:
        logger.warning(
            f"{self.base_str}: Received Notice of Cancellation for transaction {transaction_id!r} "
            f"with condition code {cond!r}. Progress: {progress}"
        )

    def abandoned_cb(
        self, transaction_id: TransactionId, cond: ConditionCode, progress: int
    ) -> None:
        logger.warning(
            f"{self.base_str}: Abandoned fault for transaction {transaction_id!r} "
            f"with condition code {cond!r}. Progress: {progress}"
        )

    def ignore_cb(self, transaction_id: TransactionId, cond: ConditionCode, progress: int) -> None:
        logger.warning(
            f"{self.base_str}: Ignored fault for transaction {transaction_id!r} "
            f"with condition code {cond!r}. Progress: {progress}"
        )


class CfdpUser(CfdpUserBase):
    DIRECTORY_LISTING_FILE = Path("c3_dirlist_0")

    def __init__(self, file_cache: CacheStore, base_str: str, put_req_queue: SimpleQueue):
        self.base_str = base_str
        self.put_req_queue = put_req_queue
        # This is a dictionary where the key is the current transaction ID for a transaction which
        # was triggered by a proxy request with an originating ID.
        self.active_proxy_put_reqs: dict[TransactionId, TransactionId] = {}
        super().__init__(file_cache)

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
        elif reserved_cfdp_msg.is_directory_operation():
            self._handle_directory_operation(transaction_id, reserved_cfdp_msg)
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
                dest_file=Path(put_req_params.dest_file_as_path),
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

    def _handle_directory_operation(
        self, transaction_id: TransactionId, reserved_cfdp_msg: ReservedCfdpMessage
    ) -> None:
        params = reserved_cfdp_msg.get_dir_listing_request_params()
        if (
            reserved_cfdp_msg.get_directory_operation_type()
            == DirectoryOperationMessageType.LISTING_REQUEST
        ):
            resp = self.vfs.list_directory(
                params.dir_path_as_path, self.DIRECTORY_LISTING_FILE, False
            )
            # FIXME: This fixes an issue with DirectoryListingResponse spacepackets <= 0.31.0.
            # Remove this once we are on 0.32.0
            value = (
                bytes([0x00 if resp == FilestoreResult.SUCCESS else 0x80])
                + params.dir_path.pack()
                + params.dir_file_name.pack()
            )
            mtu_response = ReservedCfdpMessage(
                DirectoryOperationMessageType.LISTING_RESPONSE, value
            )

            put_req = PutRequest(
                destination_id=transaction_id.source_id,
                source_file=self.DIRECTORY_LISTING_FILE,
                dest_file=params.dir_file_name_as_path,
                trans_mode=None,
                closure_requested=True,
                msgs_to_user=[
                    mtu_response.to_generic_msg_to_user_tlv(),
                    OriginatingTransactionId(transaction_id).to_generic_msg_to_user_tlv(),
                ],
            )
            self.put_req_queue.put(put_req)
        elif (
            reserved_cfdp_msg.get_directory_operation_type()
            == DirectoryOperationMessageType.LISTING_RESPONSE
        ):
            dir_list_response_params = reserved_cfdp_msg.get_dir_listing_response_params()
            logger.info(f"Received Directory Listing Response: {dir_list_response_params}")

    def file_segment_recv_indication(self, params: FileSegmentRecvdParams) -> None:
        logger.info(f"{self.base_str}: File-Segment-Recv.indication for {params.transaction_id}.")

    def report_indication(
        self,
        transaction_id: TransactionId,
        status_report,
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


class CustomCheckTimerProvider(CheckTimerProvider):
    def provide_check_timer(
        self,
        local_entity_id: ByteFieldU8,
        remote_entity_id: ByteFieldU8,
        entity_type: EntityType,
    ) -> Countdown:
        return Countdown(timedelta(seconds=5.0))


class SourceEntityHandler(Thread):
    BASE_STR_SRC = "Source id"

    def __init__(
        self,
        put_req_queue: SimpleQueue,
        source_entity_queue: SimpleQueue,
        tm_queue: SimpleQueue,
        file_cache: CacheStore,
        remote_entities: RemoteEntityConfigTable,
        gnd_id: ByteFieldU8,
        sat_id: ByteFieldU8,
        stop_signal: Event,
    ):
        super().__init__()
        src_seq_count_provider = SeqCountProvider(16)
        src_user = CfdpUser(file_cache, self.BASE_STR_SRC + sat_id.__str__(), put_req_queue)
        check_timer_provider = CustomCheckTimerProvider()
        self.source_handler = VfsSourceHandler(
            cfg=LocalEntityConfig(
                sat_id, IndicationConfig(), CfdpFaultHandler(self.BASE_STR_SRC + sat_id.__str__())
            ),
            seq_num_provider=src_seq_count_provider,
            remote_cfg_table=remote_entities,
            user=src_user,
            check_timer_provider=check_timer_provider,
        )

        self.put_req_queue = put_req_queue
        self.source_entity_queue = source_entity_queue
        self.tm_queue = tm_queue
        self.gnd_id = gnd_id
        self.sat_id = sat_id
        self.stop_signal = stop_signal

    def _idle_handling(self) -> bool:
        try:
            put_req: PutRequest = self.put_req_queue.get(False)
            logger.info(f"Handling Put Request: {put_req}")
            if put_req.destination_id not in [self.sat_id, self.gnd_id]:
                logger.warning(
                    f"can only handle put requests target towards {self.gnd_id} or {self.sat_id}"
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
            logger.debug(f"Source received {packet}")
        try:
            fsm_result = self.source_handler.state_machine(packet)
        except InvalidDestinationId as e:
            logger.warning(
                f"invalid destination ID {e.found_dest_id} on packet {packet}, expected "
                f"{e.expected_dest_id}"
            )
            fsm_result = self.source_handler.state_machine(None)
        except PduIgnoredForSource as e:
            logger.warning(f"Ignoring PDU: {e.reason}")
            fsm_result = self.source_handler.state_machine(None)
        packet_sent = False
        if fsm_result.states.num_packets_ready > 0:
            while fsm_result.states.num_packets_ready > 0:
                next_pdu_wrapper = self.source_handler.get_next_packet()
                assert next_pdu_wrapper is not None
                logger.debug(f"Sending packet {next_pdu_wrapper.pdu}")
                # Send all packets which need to be sent.
                self.tm_queue.put(next_pdu_wrapper)
                packet_sent = True
        return packet_sent

    def run(self) -> None:
        logger.info("Starting Source Entity Handler")
        while True:
            if self.stop_signal.is_set():
                logger.info(f"Stopping Source Entity Handler. Local ID {self.sat_id}")
                break
            if self.source_handler.state == CfdpState.IDLE and not self._idle_handling():
                time.sleep(1)
                continue
            if self.source_handler.state == CfdpState.BUSY and not self._busy_handling():
                time.sleep(0.1)

    def set_seq_num(self, new: int) -> None:
        self.source_handler.seq_num_provider.count = new

    def get_seq_num(self) -> int:
        return self.source_handler.seq_num_provider.count


class DestEntityHandler(Thread):
    BASE_STR_DEST = "Dest id"

    def __init__(
        self,
        put_req_queue: SimpleQueue,
        dest_entity_queue: SimpleQueue,
        tm_queue: SimpleQueue,
        file_cache: CacheStore,
        remote_entities: RemoteEntityConfigTable,
        sat_id: ByteFieldU8,
        stop_signal: Event,
    ):
        super().__init__()

        dest_user = CfdpUser(file_cache, self.BASE_STR_DEST + sat_id.__str__(), put_req_queue)
        check_timer_provider = CustomCheckTimerProvider()
        self.dest_handler = FixedDestHandler(
            cfg=LocalEntityConfig(
                sat_id, IndicationConfig(), CfdpFaultHandler(self.BASE_STR_DEST + sat_id.__str__())
            ),
            user=dest_user,
            remote_cfg_table=remote_entities,
            check_timer_provider=check_timer_provider,
        )

        self.dest_entity_queue = dest_entity_queue
        self.tm_queue = tm_queue
        self.sat_id = sat_id
        self.stop_signal = stop_signal

    def run(self) -> None:
        logger.info(f"Starting Dest Entity Handler. Local ID {self.sat_id}")
        while True:
            packet_received = False
            packet = None
            if self.stop_signal.is_set():
                logger.info(f"Stopping Dest Entity Handler. Local ID {self.sat_id}")
                break
            try:
                packet = self.dest_entity_queue.get(False)
                packet_received = True
            except Empty:
                pass
            if packet is not None:
                logger.debug(f"Dest received {packet}")
            try:
                fsm_result = self.dest_handler.state_machine(packet)
            except PduIgnoredForDest as e:
                logger.warning(f"Ignoring PDU: {e.reason}")
            packet_sent = False
            if fsm_result.states.num_packets_ready > 0:
                while fsm_result.states.num_packets_ready > 0:
                    next_pdu_wrapper = self.dest_handler.get_next_packet()
                    assert next_pdu_wrapper is not None
                    logger.debug(f"Sending packet {next_pdu_wrapper.pdu}")
                    self.tm_queue.put(next_pdu_wrapper)
                    packet_sent = True
            # If there is no work to do, put the thread to sleep.
            if not packet_received and not packet_sent:
                time.sleep(0.1)
