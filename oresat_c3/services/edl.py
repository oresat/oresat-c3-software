"""'EDL Service"""

from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from time import time
from typing import Any, Callable, Optional

import canopen
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
from olaf import MasterNode, NodeStop, Service, logger
from oresat_configs import EdlCommandDefinitions
from spacepackets.cfdp import ChecksumType, ConditionCode, FaultHandlerCode, TransmissionMode
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

from ..protocols.cachestore import CacheStore
from ..protocols.cfdp import FixedDestHandler, VfsCrcHelper, VfsSourceHandler
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError, EdlVcid
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time
from .beacon import BeaconService
from .node_manager import NodeManagerService
from .radios import RadiosService


class EdlService(Service):
    """'EDL Service"""

    def __init__(
        self,
        cmd_defs: EdlCommandDefinitions,
        node: MasterNode,
        radios_service: RadiosService,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
    ):
        super().__init__()

        self._radios_service = radios_service
        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service

        self._file_receiver = EdlFileReciever(node.fwrite_cache)

        self._cmd_defs = cmd_defs
        self._cmd_funcs: dict[str, Callable] = {
            "tx_control": self._run_cmd_tx_control,
            "c3_soft_reset": self._run_cmd_soft_reset,
            "c3_hard_reset": self._run_cmd_hard_reset,
            "c3_factory_reset": self._run_cmd_factory_reset,
            "co_node_enable": self._run_cmd_node_enable,
            "co_node_status": self._run_cmd_node_status,
            "co_sdo_write": self._run_cmd_sdo_write,
            "co_sync": self._run_cmd_sync,
            "opd_sysenable": self._run_cmd_opd_sysenable,
            "opd_scan": self._run_cmd_opd_scan,
            "opd_probe": self._run_cmd_opd_probe,
            "opd_status": self._run_cmd_opd_status,
            "opd_reset": self._run_cmd_opd_reset,
            "opd_enable": self._run_cmd_opd_enable,
            "rtc_set_time": self._run_cmd_rtc_time,
            "time_sync": self._run_cmd_time_sync,
            "beacon_ping": self._run_cmd_beacon_ping,
            "ping": self._run_cmd_ping,
            "rx_test": self._run_cmd_rx_test,
            "co_sdo_read": self._run_cmd_sdo_read,
        }

    def _upack_last_recv(self) -> Optional[EdlPacket]:
        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return None

        flight_mode = self.node.od_read("flight_mode", None)
        active_key = self.node.od_read("edl", "active_crypto_key")
        hmac_key = self.node.od_read("edl", f"crypto_key_{active_key}")

        try:
            packet = EdlPacket.unpack(message, hmac_key, not flight_mode)
        except EdlPacketError as e:
            rejected_count = self.node.od_read("edl", "rejected_count")
            rejected_count += 1
            rejected_count &= 0xFF_FF_FF_FF
            self.node.od_write("edl", "rejected_count", rejected_count)
            logger.error(f"invalid EDL request packet: {e}")
            return None  # no responses to invalid packets

        sequence_count = self.node.od_read("edl", "sequence_count")

        if flight_mode and packet.seq_num < sequence_count:
            logger.error(
                f"invalid EDL request packet sequence number of {packet.seq_num}, should be > "
                f"{sequence_count}"
            )
            return None  # no responses to invalid packets

        self.node.od_write("edl", "last_timestamp", int(time()))

        if flight_mode:
            self.node.od_write("edl", "sequence_count", packet.seq_num)

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
            res_payload = self._run_cmd(req_packet.payload[0], req_packet.payload[1:])
            if res_payload is None:
                return  # no response
        elif req_packet.vcid == EdlVcid.FILE_TRANSFER:
            res_payload = self._file_receiver.loop(req_packet.payload)
        else:
            logger.error(f"got an EDL packet with unknown VCID: {req_packet.vcid}")
            return

        if res_payload is None:
            self.sleep_ms(50)
            return

        active_key = self.node.od_read("edl", "active_crypto_key")
        hmac_key = self.node.od_read("edl", f"crypto_key_{active_key}")

        if not isinstance(res_payload, tuple):
            res_payload = (res_payload,)
        for payload in res_payload:
            try:
                res_packet = EdlPacket(payload, req_packet.seq_num, SRC_DEST_UNICLOGS)
                res_message = res_packet.pack(hmac_key)
            except (EdlPacketError, ValueError) as e:
                logger.exception(f"EDL response generation raised: {e}")
                continue

            self._radios_service.send_edl_response(res_message)

    def _run_cmd(self, cmd_code: int, payload: bytes) -> Optional[bytes]:
        if cmd_code not in self._cmd_defs:
            logger.info(f"invalid edl command code {cmd_code}")
            return None
        cmd = self._cmd_defs[cmd_code]

        try:
            req_args = cmd.decode_request(payload)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"EDL command {cmd.name} decode request raised: {e}")
            return None

        try:
            if req_args is None:
                res_data = self._cmd_funcs[cmd.name]()
            else:
                res_data = self._cmd_funcs[cmd.name](*req_args)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"EDL command {cmd.name} function raised: {e}")
            return None

        if res_data is None:
            return None
        if not isinstance(res_data, tuple):
            res_data = (res_data,)

        try:
            res_payload = bytes([cmd_code]) + cmd.encode_response(res_data)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"EDL command {cmd.name} encode response raised: {e}")
            return None

        return res_payload

    def _run_cmd_tx_control(self, enable: bool) -> bool:
        if enable is True:
            logger.info("EDL disabling Tx")
            new_time = 0
        else:
            logger.info("EDL enabling Tx")
            new_time = int(time())
        self.node.od_write("tx_control", "enable", enable)
        self.node.od_write("tx_control", "last_enable_timestamp", new_time)
        return enable

    def _run_cmd_soft_reset(self):
        logger.info("EDL soft reset")
        self.node.stop(NodeStop.SOFT_RESET)

    def _run_cmd_hard_reset(self):
        logger.info("EDL hard reset")
        self.node.stop(NodeStop.HARD_RESET)

    def _run_cmd_factory_reset(self):
        logger.info("EDL factory reset")
        self.node.stop(NodeStop.FACTORY_RESET)

    def _run_cmd_node_enable(self, node_id) -> int:
        name = self._node_mgr_service.node_id_to_name[node_id]
        logger.info(f"EDL enabling CANopen node {name} (0x{node_id:02X})")
        return self.node.node_status[name]

    def _run_cmd_node_status(self, node_id: int) -> int:
        name = self._node_mgr_service.node_id_to_name[node_id]
        logger.info(f"EDL getting CANopen node {name} (0x{node_id:02X}) status")
        return self.node.node_status[name]

    def _run_cmd_sdo_write(self, node_id: int, index: int, subindex: int, data: bytes) -> int:
        name = self._node_mgr_service.node_id_to_name[node_id]
        logger.info(f"EDL SDO read on CANopen node {name} (0x{node_id:02X})")
        try:
            if node_id == 1:
                var_index = isinstance(self.node.od[index], canopen.objectdictionary.Variable)
                if var_index and subindex == 0:
                    obj = self.node.od[index]
                elif not var_index:
                    obj = self.node.od[index][subindex]
                else:
                    raise canopen.sdo.exceptions.SdoAbortedError(0x06090011)
                self.node._on_sdo_write(index, subindex, obj, data)  # pylint: disable=W0212
            else:
                self.node.sdo_write(name, index, subindex, data)
            ret = 0
        except canopen.sdo.exceptions.SdoAbortedError as e:
            logger.error(e)
            ret = e.code

        return ret

    def _run_cmd_sync(self):
        logger.info("EDL sending CANopen SYNC message")
        self.node.send_sync()

    def _run_cmd_opd_sysenable(self, enable: bool) -> bool:
        if enable is True:
            logger.info("EDL enabling OPD subsystem")
            self._node_mgr_service.opd.enable()
        else:
            logger.info("EDL disabling OPD subsystem")
            self._node_mgr_service.opd.disable()
        return self._node_mgr_service.opd.status.value

    def _run_cmd_opd_scan(self) -> int:
        logger.info("EDL scaning for all OPD nodes")
        return self._node_mgr_service.opd.scan()

    def _run_cmd_opd_probe(self, opd_addr: int) -> int:
        name = self._node_mgr_service.opd_addr_to_name[opd_addr]
        logger.info(f"EDL probing for OPD node {name} (0x{opd_addr:02X})")
        return self._node_mgr_service.opd[name].probe()

    def _run_cmd_opd_enable(self, opd_addr: int, enable: bool) -> int:
        name = self._node_mgr_service.opd_addr_to_name[opd_addr]
        node = self._node_mgr_service.opd[name]
        if enable is True:
            logger.info(f"EDL disabling OPD node {name} (0x{opd_addr:02X})")
            node.disable()
        else:
            logger.info(f"EDL enabling OPD node {name} (0x{opd_addr:02X})")
            node.enable()
        return node.status.value

    def _run_cmd_opd_reset(self, opd_addr: int) -> int:
        name = self._node_mgr_service.opd_addr_to_name[opd_addr]
        logger.info(f"EDL resetting OPD node {name} (0x{opd_addr:02X})")
        node = self._node_mgr_service.opd[name]
        node.reset()
        return node.status.value

    def _run_cmd_opd_status(self, opd_addr: int) -> int:
        name = self._node_mgr_service.opd_addr_to_name[opd_addr]
        logger.info(f"EDL getting the status for OPD node {name} (0x{opd_addr:02X})")
        return self._node_mgr_service.opd[name].status.value

    def _run_cmd_rtc_time(self, ts: int):
        logger.info(f"EDL setting the RTC time to {ts}")
        set_rtc_time(ts)
        set_system_time_to_rtc_time()

    def _run_cmd_time_sync(self):
        logger.info("EDL sending time sync TPDO")
        self.node.send_tpdo(0)

    def _run_cmd_beacon_ping(self):
        logger.info("EDL beacon")
        self._beacon_service.send()

    def _run_cmd_ping(self, value: int) -> int:
        logger.info(f"EDL ping {value}")
        return value

    def _run_cmd_rx_test(self):
        logger.info("EDL Rx test")

    def _run_cmd_sdo_read(self, node_id: int, index: int, subindex: int) -> tuple[int, bytes]:
        name = self._node_mgr_service.node_id_to_name[node_id]
        logger.info(f"EDL SDO read on CANopen node {name} (0x{node_id:02X})")
        data = b""
        ecode = 0
        try:
            if node_id == 1:
                var_index = isinstance(self.node.od[index], canopen.objectdictionary.Variable)
                if var_index and subindex == 0:
                    obj = self.node.od[index]
                elif not var_index:
                    obj = self.node.od[index][subindex]
                else:
                    raise canopen.sdo.exceptions.SdoAbortedError(0x06090011)
                value = self.node._on_sdo_read(index, subindex, obj)  # pylint: disable=W0212
                data = obj.encode_raw(value)
            else:
                value = self.node.sdo_read(name, index, subindex)
                od = self.node.od_db[name]
                var_index = isinstance(od[index], canopen.objectdictionary.Variable)
                if var_index and subindex == 0:
                    obj = od[index]
                elif not var_index:
                    obj = od[index][subindex]
                else:
                    raise canopen.sdo.exceptions.SdoAbortedError(0x06090011)
                data = obj.encode_raw(value)
        except canopen.sdo.exceptions.SdoAbortedError as e:
            logger.error(e)
            ecode = e.code
        return (ecode, data)


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

    def __init__(self, fwrite_cache: CacheStore):
        super().__init__(vfs=fwrite_cache)

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
            ConditionCode.POSITIVE_ACK_LIMIT_REACHED, FaultHandlerCode.ABANDON_TRANSACTION
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
