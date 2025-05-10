from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from time import time
from typing import Any, Optional

from cfdppy import CfdpState, PacketDestination, get_packet_destination
from cfdppy.exceptions import NoRemoteEntityCfgFound, SourceFileDoesNotExist
from cfdppy.mib import (
    CheckTimerProvider,
    DefaultFaultHandlerBase,
    IndicationCfg,
    LocalEntityCfg,
    RemoteEntityCfg,
    RemoteEntityCfgTable,
)
from cfdppy.request import PutRequest
from cfdppy.user import (
    CfdpUserBase,
    FileSegmentRecvdParams,
    MetadataRecvParams,
    TransactionFinishedParams,
    TransactionId,
    TransactionParams,
)
from loguru import logger
from oresat_cand import NodeClient
from spacepackets.cfdp import (
    ChecksumType,
    ConditionCode,
    FaultHandlerCode,
    TransmissionMode,
)
from spacepackets.cfdp.defs import DeliveryCode, FileStatus
from spacepackets.cfdp.pdu import AbstractFileDirectiveBase
from spacepackets.cfdp.tlv import (
    DirectoryListingResponse,
    DirectoryOperationMessageType,
    OriginatingTransactionId,
    ProxyMessageType,
    ProxyPutResponse,
    ProxyPutResponseParams,
)
from spacepackets.countdown import Countdown
from spacepackets.seqcount import SeqCountProvider
from spacepackets.util import ByteFieldU8

from ..gen.c3_od import C3Entry, C3SystemReset
from ..protocols.cfdp import FixedDestHandler, VfsCrcHelper, VfsSourceHandler
from ..protocols.edl_command import (
    EdlCommandCode,
    EdlCommandError,
    EdlCommandRequest,
    EdlCommandResponse,
)
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError, EdlVcid
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time
from . import Service
from .beacon import BeaconService
from .node_manager import NodeManagerService
from .radios import RadiosService


class EdlService(Service):
    """'EDL Service"""

    def __init__(
        self,
        node: NodeClient,
        radios_service: RadiosService,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
    ):
        super().__init__(node)

        self._radios_service = radios_service
        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service

        self._file_receiver = EdlFileReciever()

        self._active_key_entry = C3Entry.EDL_CRYPTO_KEY_1

    @property
    def _hmac_key(self) -> bytes:
        return self.node.od_read(self._active_key_entry)

    def _increase_count(self, entry):
        count = self.node.od_read(entry)
        count += 1
        count &= 0xFF_FF_FF_FF
        self.node.od_write(entry, count)

    def _set_active_key(self, key_num: int):
        self.node.od_write(C3Entry.EDL_ACTIVE_CRYPTO_KEY, key_num)
        key_entries = [
            C3Entry.EDL_CRYPTO_KEY_0,
            C3Entry.EDL_CRYPTO_KEY_1,
            C3Entry.EDL_CRYPTO_KEY_2,
            C3Entry.EDL_CRYPTO_KEY_3,
        ]
        self._active_key_entry = key_entries[key_num]

    def _upack_last_recv(self) -> Optional[EdlPacket]:
        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return None

        try:
            packet = EdlPacket.unpack(
                message, self._hmac_key, not self.node.od_read(C3Entry.FLIGHT_MODE)
            )
        except EdlPacketError as e:
            logger.error(f"invalid EDL request packet: {e}")
            self._increase_count(C3Entry.EDL_REJECTED_COUNT)
            return None  # no responses to invalid packets

        if self.node.od_read(C3Entry.FLIGHT_MODE) and packet.seq_num < self.node.od_read(
            C3Entry.EDL_SEQUENCE_COUNT
        ):
            logger.error(
                f"invalid EDL request packet sequence number of {packet.seq_num}, should be > "
                f"{self.node.od_read(C3Entry.EDL_SEQUENCE_COUNT)}"
            )
            return None  # no responses to invalid packets

        self.node.od_read(C3Entry.EDL_LAST_TIMESTAMP, int(time()))

        if self.node.od_read(C3Entry.FLIGHT_MODE):
            self._increase_count(C3Entry.EDL_SEQUENCE_COUNT)

        return packet

    def on_loop(self):
        req_packet = self._upack_last_recv()

        if req_packet is None:
            if self._file_receiver.state == CfdpState.BUSY:
                res_payload = self._file_receiver.loop(None)
            else:
                self.sleep_ms(50)
                return
        elif req_packet.vcid == EdlVcid.C3_COMMAND:
            try:
                res_payload = self._run_cmd(req_packet.payload)
                if not res_payload.values:
                    return  # no response
            except Exception as e:  # pylint: disable=W0718
                logger.error(f"EDL command {req_packet.payload.code.name} raised: {e}")
                return
        elif req_packet.vcid == EdlVcid.FILE_TRANSFER:
            res_payload = self._file_receiver.loop(req_packet.payload)
        else:
            logger.error(f"got an EDL packet with unknown VCID: {req_packet.vcid}")
            return

        if res_payload is None:
            self.sleep_ms(50)
            return

        if not isinstance(res_payload, Iterable):
            res_payload = (res_payload,)
        for payload in res_payload:
            try:
                res_packet = EdlPacket(payload, self._sequence_count, SRC_DEST_UNICLOGS)
                res_message = res_packet.pack(self._hmac_key)
            except (EdlCommandError, EdlPacketError, ValueError) as e:
                logger.exception(f"EDL response generation raised: {e}")
                continue

            self._radios_service.send_edl_response(res_message)

    def _run_cmd(self, request: EdlCommandRequest) -> EdlCommandResponse:
        ret: Any = None

        logger.info(f"EDL command request: {request.code.name}, args: {request.args}")

        if request.code == EdlCommandCode.TX_CTRL:
            if request.args[0] == 0:
                logger.info("EDL disabling Tx")
                self.node.od_write(C3Entry.TX_CONTROL_ENABLE, False)
                self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, 0)
                ret = False
            else:
                logger.info("EDL enabling Tx")
                self.node.od_write(C3Entry.TX_CONTROL_ENABLE, True)
                self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, int(time()))
                ret = True
        elif request.code == EdlCommandCode.C3_SOFT_RESET:
            logger.info("EDL soft reset")
            self.node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.SOFT_RESET)
        elif request.code == EdlCommandCode.C3_HARD_RESET:
            logger.info("EDL hard reset")
            self.node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.HARD_RESET)
        elif request.code == EdlCommandCode.C3_FACTORY_RESET:
            logger.info("EDL factory reset")
            self.node.od_write(C3Entry.SYSTEM_RESET, C3SystemReset.FACTORY_RESET)
        elif request.code == EdlCommandCode.CO_NODE_ENABLE:
            node_id = request.args[0]
            name = self._node_mgr_service.node_id_to_name[node_id]
            logger.info(f"EDL enabling CANopen node {name} (0x{node_id:02X})")
        elif request.code == EdlCommandCode.CO_NODE_STATUS:
            node_id = request.args[0]
            name = self._node_mgr_service.node_id_to_name[node_id]
            logger.info(f"EDL getting CANopen node {name} (0x{node_id:02X}) status")
            ret = self.node.node_status[name]
        elif request.code == EdlCommandCode.CO_SDO_WRITE:
            node_id, index, subindex, _, data = request.args
            name = self._node_mgr_service.node_id_to_name[node_id]
            logger.info(f"EDL SDO read on CANopen node {name} (0x{node_id:02X})")
            try:
                if node_id == 1:
                    entry = C3Entry.find_entry(index, subindex)
                    value = entry.decode(data)
                    self.node.sdo_write(node_id, entry, value)
                else:
                    raise NotImplementedError()
                ret = 0
            except Exception as e:
                logger.error(e)
                ret = 1
        elif request.code == EdlCommandCode.CO_SYNC:
            logger.info("EDL sending CANopen SYNC message")
            self.node.send_sync()
        elif request.code == EdlCommandCode.OPD_SYSENABLE:
            enable = request.args[0]
            if enable:
                logger.info("EDL enabling OPD subsystem")
                self._node_mgr_service.opd.enable()
            else:
                logger.info("EDL disabling OPD subsystem")
                self._node_mgr_service.opd.disable()
            ret = self._node_mgr_service.opd.status.value
        elif request.code == EdlCommandCode.OPD_SCAN:
            logger.info("EDL scaning for all OPD nodes")
            ret = self._node_mgr_service.opd.scan()
        elif request.code == EdlCommandCode.OPD_PROBE:
            opd_addr = request.args[0]
            name = self._node_mgr_service.opd_addr_to_name[opd_addr]
            logger.info(f"EDL probing for OPD node {name} (0x{opd_addr:02X})")
            ret = self._node_mgr_service.opd[name].probe()
        elif request.code == EdlCommandCode.OPD_ENABLE:
            opd_addr = request.args[0]
            name = self._node_mgr_service.opd_addr_to_name[opd_addr]
            node = self._node_mgr_service.opd[name]
            if request.args[1] == 0:
                logger.info(f"EDL disabling OPD node {name} (0x{opd_addr:02X})")
                ret = node.disable()
            else:
                logger.info(f"EDL enabling OPD node {name} (0x{opd_addr:02X})")
                ret = node.enable()
            ret = node.status.value
        elif request.code == EdlCommandCode.OPD_RESET:
            opd_addr = request.args[0]
            name = self._node_mgr_service.opd_addr_to_name[opd_addr]
            logger.info(f"EDL resetting OPD node {name} (0x{opd_addr:02X})")
            node = self._node_mgr_service.opd[name]
            node.reset()
            ret = node.status.value
        elif request.code == EdlCommandCode.OPD_STATUS:
            opd_addr = request.args[0]
            name = self._node_mgr_service.opd_addr_to_name[opd_addr]
            logger.info(f"EDL getting the status for OPD node {name} (0x{opd_addr:02X})")
            ret = self._node_mgr_service.opd[name].status.value
        elif request.code == EdlCommandCode.RTC_SET_TIME:
            ts = request.args[0]
            logger.info(f"EDL setting the RTC time to {ts}")
            set_rtc_time(ts)
            set_system_time_to_rtc_time()
        elif request.code == EdlCommandCode.TIME_SYNC:
            logger.info("EDL sending time sync TPDO")
            self.node.send_tpdo(0)
        elif request.code == EdlCommandCode.BEACON_PING:
            logger.info("EDL beacon")
            self._beacon_service.send()
        elif request.code == EdlCommandCode.PING:
            logger.info("EDL ping")
            ret = request.args[0]
        elif request.code == EdlCommandCode.RX_TEST:
            logger.info("EDL Rx test")
        elif request.code == EdlCommandCode.CO_SDO_READ:
            node_id, index, subindex = request.args
            name = self._node_mgr_service.node_id_to_name[node_id]
            logger.info(f"EDL SDO read on CANopen node {name} (0x{node_id:02X})")
            data = b""
            ecode = 0
            try:
                if node_id == 1:
                    entry = C3Entry.find_entry(index, subindex)
                    value = self.node.sdo_read(node_id, entry)
                    data = entry.encode(value)
                else:
                    raise NotImplementedError()
            except canopen.sdo.exceptions.SdoAbortedError as e:
                logger.error(e)
                ecode = e.code
            except Exception as e:
                logger.error(e)
                ecode = 0x06090011
            ret = (ecode, len(data), data)

        if ret is not None and not isinstance(ret, tuple):
            ret = (ret,)  # make ret a tuple

        response = EdlCommandResponse(request.code, ret)

        logger.info(f"EDL command response: {response.code.name}, values: {response.values}")

        return response


class LogFaults(DefaultFaultHandlerBase):
    """A HaultHandler that only logs the faults and nothing more.

    At some point this should be replaced with something more robust.
    """

    def notice_of_suspension_cb(self, transaction_id, cond, progress):
        logger.info(f"Transaction {transaction_id} suspended: {cond}. Progress {progress}")

    def notice_of_cancellation_cb(self, transaction_id, cond, progress):
        logger.info(f"Transaction {transaction_id} cancelled: {cond}. Progress {progress}")

    def abandoned_cb(self, transaction_id, cond, progress):
        logger.info(f"Transaction {transaction_id} abandoned: {cond}. Progress {progress}")

    def ignore_cb(self, transaction_id, cond, progress):
        logger.info(f"Transaction {transaction_id} ignored: {cond}. Progress {progress}")


class DefaultCheckTimer(CheckTimerProvider):
    """A straight copy of the example CheckTimerProvider

    I think this exists to possibly account for the latency between local and remote entities?
    Unfortunately it doesn't get used for all the timers in source/dest, like the ACK timer.
    """

    def provide_check_timer(self, local_entity_id, remote_entity_id, entity_type) -> Countdown:
        return Countdown(timedelta(seconds=5.0))


class EdlFileReciever(CfdpUserBase):
    """CFDP receiver for file uploads."""

    def __init__(self):
        super().__init__()

        self.proxy_responses = {  # FIXME: defaultdict with invalid response
            ProxyMessageType.PUT_REQUEST: self.proxy_put_response,
            ProxyMessageType.MSG_TO_USER: self.unimplemented,
            ProxyMessageType.FS_REQUEST: self.unimplemented,
            ProxyMessageType.FAULT_HANDLER_OVERRIDE: self.unimplemented,
            ProxyMessageType.TRANSMISSION_MODE: self.unimplemented,
            ProxyMessageType.FLOW_LABEL: self.unimplemented,
            ProxyMessageType.SEGMENTATION_CTRL: self.unimplemented,
            ProxyMessageType.PUT_RESPONSE: self.unimplemented,
            ProxyMessageType.FS_RESPONSE: self.unimplemented,
            ProxyMessageType.PUT_CANCEL: self.unimplemented,
            ProxyMessageType.CLOSURE_REQUEST: self.unimplemented,
            DirectoryOperationMessageType.LISTING_REQUEST: self.directory_listing_response,
            DirectoryOperationMessageType.LISTING_RESPONSE: self.unimplemented,
            DirectoryOperationMessageType.CUSTOM_LISTING_PARAMETERS: self.unimplemented,
        }

        SOURCE_ID = ByteFieldU8(0)
        DEST_ID = ByteFieldU8(1)
        fault_handler = LogFaults()
        # The default setting is NOTICE_OF_CANCELLATION but during that process the positive ack
        # counter gets reset, meaning we keep retrying the handler forever. This manifests for
        # example if the final source -> dest ack for FinishedPDU gets dropped. Source considers
        # the transaction finished, and will refuse to respond, dest will be stuck re-sending the
        # FinishedPDU every ack_timer interval forever. Setting it to ABANDON_TRANSACTION means it
        # just resets after the ack counter reaches its count.
        fault_handler.set_handler(
            ConditionCode.POSITIVE_ACK_LIMIT_REACHED,
            FaultHandlerCode.ABANDON_TRANSACTION,
        )

        localcfg = LocalEntityCfg(
            local_entity_id=DEST_ID,
            indication_cfg=IndicationCfg(),
            default_fault_handlers=fault_handler,
        )

        remote_entities = RemoteEntityCfgTable(
            [
                RemoteEntityCfg(
                    entity_id=SOURCE_ID,
                    max_file_segment_len=None,
                    # FIXME this value should come from EdlPacket but EdlPacket does not define it.
                    # How does the exact value get determined? Currently it's just a mirror of the
                    # value in edl_file_upload.py
                    max_packet_len=950,
                    closure_requested=False,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.CRC_32,
                ),
            ]
        )

        self.dest = FixedDestHandler(
            cfg=localcfg,
            user=self,
            remote_cfg_table=remote_entities,
            check_timer_provider=DefaultCheckTimer(),
        )
        self.dest._cksum_verif_helper = VfsCrcHelper(ChecksumType.NULL_CHECKSUM, self.vfs)

        self.source = VfsSourceHandler(
            cfg=localcfg,
            user=self,
            remote_cfg_table=remote_entities,
            check_timer_provider=DefaultCheckTimer(),
            seq_num_provider=SeqCountProvider(16),
        )
        self.source._crc_helper = VfsCrcHelper(ChecksumType.NULL_CHECKSUM, self.vfs)

        self.scheduled_requests: SimpleQueue[PutRequest] = SimpleQueue()
        self.active_requests: dict[TransactionId, TransactionId] = {}

    @property
    def state(self) -> CfdpState:
        """Either BUSY or IDLE

        The FileReceiver is BUSY if either source or dest are busy, or if there's a request yet
        to be initiated.
        """

        if (
            self.dest.state == CfdpState.BUSY
            or self.source.state == CfdpState.BUSY
            or not self.scheduled_requests.empty()
        ):
            return CfdpState.BUSY
        return CfdpState.IDLE

    def loop(self, pdu: AbstractFileDirectiveBase):
        """The state machine driver for a CFDP dest, expected to be run by the service loop"""

        # DestHandler is driven by either a new pdu to process or timers expiring and
        # SourceHandler is additionally driven by Put requests.
        # Timers only expire when .state_machine() is called, and .state_machine() must
        # be called after all the packets have been drained, or after inserting a new
        # pdu.
        if pdu:
            logger.info(f"<--- {pdu}")

            if get_packet_destination(pdu) == PacketDestination.DEST_HANDLER:
                try:
                    self.dest.insert_packet(pdu)
                except Exception:
                    # Usually this exception means the library is being used wrong, so we have
                    # to be careful here. However there is a bug in the presence of dropped packets
                    # where dest._params.last_inserted_packet does not get cleared.
                    logger.exception("dest.state_machine() didn't properly clear inserted packet")
                    self.dest.reset()
            else:
                try:
                    self.source.insert_packet(pdu)
                except Exception:
                    logger.exception("source.state_machine() didn't properly clear inserted packet")
                    self.source.reset()

        if self.dest.state == CfdpState.IDLE and self.source.state == CfdpState.IDLE:
            try:
                request = self.scheduled_requests.get_nowait()
            except Empty:
                pass
            else:
                try:
                    self.source.put_request(request)
                except (SourceFileDoesNotExist, NoRemoteEntityCfgFound):
                    # Note that NoRemoteEntityCfgFound indicates that the MIB is missing info on
                    # the requested proxy transfer destination. CFDP doesn't seem to have a
                    # standard set of errors that cover this condition, and the least worst option
                    # resulted in an identical message to missing_file. Not super great, so if
                    # there's a better idea of how to handle this, please change.
                    self.scheduled_requests.put(self.missing_file_response(request))

        try:
            self.dest.state_machine()
            self.source.state_machine()
        except Exception:
            logger.exception("state_machine failed to update")
            self.dest.reset()
            self.source.reset()

        pdus = []
        while self.dest.packets_ready:
            pdus.append(self.dest.get_next_packet().pdu)
        while self.source.packets_ready:
            pdus.append(self.source.get_next_packet().pdu)

        for out in pdus:
            logger.info(f"---> {out}")
        return pdus or None

    def unimplemented(self, _source, _tid, _reserved_message) -> PutRequest:
        """Default method for responding to unimplemented requests"""
        return None

    def missing_file_response(self, invalid: PutRequest) -> PutRequest:
        """Generates a resonse put for when a proxy request tries to access a missing file"""

        originating_id = (
            invalid.msgs_to_user[0].to_reserved_msg_tlv().get_originating_transaction_id()
        )
        return PutRequest(
            destination_id=originating_id.source_id,
            source_file=None,
            dest_file=None,
            trans_mode=None,
            # FIXME: upstream bug - DestHandler does not respect closure_requested=None when
            # trans_mode defaults to ACKNOWLEGED
            closure_requested=True,
            msgs_to_user=[
                ProxyPutResponse(
                    ProxyPutResponseParams(
                        condition_code=ConditionCode.FILESTORE_REJECTION,
                        delivery_code=DeliveryCode.DATA_COMPLETE,
                        file_status=FileStatus.DISCARDED_FILESTORE_REJECTION,
                    )
                ).to_generic_msg_to_user_tlv(),
                OriginatingTransactionId(originating_id).to_generic_msg_to_user_tlv(),
            ],
        )

    def proxy_put_response(self, _source, _tid, reserved_message) -> PutRequest:
        """Response for a proxy put request"""
        params = reserved_message.get_proxy_put_request_params()
        return PutRequest(
            destination_id=params.dest_entity_id,
            source_file=Path(params.source_file_as_path),
            dest_file=Path(params.dest_file_as_path),
            trans_mode=None,
            closure_requested=True,
            msgs_to_user=[
                OriginatingTransactionId(params.transaction_id).to_generic_msg_to_user_tlv()
            ],
        )

    def directory_listing_response(self, source, tid, reserved_message) -> PutRequest:
        """Response for a directory listing request"""
        # See CFDP 6.3.4
        params = reserved_message.get_dir_listing_request_params()
        self.vfs.list_directory(params.dir_path_as_path, params.dir_file_name_as_path, False)
        return PutRequest(
            destination_id=source,
            source_file=params.dir_file_name_as_path,
            dest_file=params.dir_file_name_as_path,
            trans_mode=None,
            closure_requested=True,
            msgs_to_user=[
                DirectoryListingResponse(
                    listing_success=True,
                    dir_params=params,
                ).to_generic_msg_to_user_tlv(),
                OriginatingTransactionId(tid).to_generic_msg_to_user_tlv(),
            ],
        )

    def proxy_request_complete(self, originating_id, params) -> PutRequest:
        """Indicates that a proxy put request was successful"""
        return PutRequest(
            destination_id=originating_id.source_id,
            source_file=None,
            dest_file=None,
            trans_mode=None,
            # FIXME: upstream bug - DestHandler does not respect closure_requested=None when
            # trans_mode defaults to ACKNOWLEGED
            closure_requested=True,
            msgs_to_user=[
                ProxyPutResponse(
                    ProxyPutResponseParams.from_finished_params(params.finished_params)
                ).to_generic_msg_to_user_tlv(),
                OriginatingTransactionId(originating_id).to_generic_msg_to_user_tlv(),
            ],
        )

    def transaction_indication(self, transaction_indication_params: TransactionParams):
        logger.info(f"Indication: Transaction. {transaction_indication_params}")
        t_id = transaction_indication_params.transaction_id
        orig = transaction_indication_params.originating_transaction_id
        if orig is not None:
            self.active_requests[t_id] = orig

    def eof_sent_indication(self, transaction_id: TransactionId):
        logger.info(f"Indication: EOF Sent for {transaction_id}.")

    def transaction_finished_indication(self, params: TransactionFinishedParams):
        logger.info(f"Indication: Transaction Finished. {params}")
        if params.transaction_id in self.active_requests:
            originating_id = self.active_requests.get(params.transaction_id)
            assert originating_id is not None
            put = self.proxy_request_complete(originating_id, params)
            self.scheduled_requests.put(put)
            del self.active_requests[params.transaction_id]

    def metadata_recv_indication(self, params: MetadataRecvParams):
        logger.info(f"Indication: Metadata Recv. {params}")
        for msg in params.msgs_to_user or []:
            if r := msg.to_reserved_msg_tlv():  # is None if not a reserved TLV message
                op = r.get_cfdp_proxy_message_type() or r.get_directory_operation_type()
                put = self.proxy_responses[op](params.source_id, params.transaction_id, r)
                self.scheduled_requests.put(put)
            # Ignore non-reserved messages for now

    def file_segment_recv_indication(self, params: FileSegmentRecvdParams):
        logger.info(f"Indication: File Segment Recv. {params}")

    def report_indication(self, transaction_id: TransactionId, status_report: Any):
        logger.info(f"Indication: Report for {transaction_id}. {status_report}")

    def suspended_indication(self, transaction_id: TransactionId, cond_code: ConditionCode):
        logger.info(f"Indication: Suspended for {transaction_id}. {cond_code}")

    def resumed_indication(self, transaction_id: TransactionId, progress: int):
        logger.info(f"Indication: Resumed for {transaction_id}. {progress}")

    def fault_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        logger.info(f"Indication: Fault for {transaction_id}. {cond_code}. {progress}")

    def abandoned_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        logger.info(f"Indication: Abandoned for {transaction_id}. {cond_code}. {progress}")

    def eof_recv_indication(self, transaction_id: TransactionId):
        logger.info(f"Indication: EOF Recv for {transaction_id}")
