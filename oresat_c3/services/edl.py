"""'EDL Service"""

import struct
from collections.abc import Iterable
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from time import time
from typing import Any, Optional

import canopen
from cfdppy import CfdpState, PacketDestination, get_packet_destination
from cfdppy.exceptions import (
    FsmNotCalledAfterPacketInsertion,
    NoRemoteEntityCfgFound,
    SourceFileDoesNotExist,
)
from cfdppy.filestore import HostFilestore
from cfdppy.handler.crc import CrcHelper
from cfdppy.handler.dest import DestHandler
from cfdppy.handler.source import SourceHandler
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
from olaf import MasterNode, NodeStop, OreSatFileCache, Service, logger
from spacepackets.cfdp import NULL_CHECKSUM_U32, ChecksumType, ConditionCode, TransmissionMode
from spacepackets.cfdp.defs import DeliveryCode, FileStatus
from spacepackets.cfdp.pdu import AbstractFileDirectiveBase
from spacepackets.cfdp.tlv import (
    FilestoreResponseStatusCode,
    OriginatingTransactionId,
    ProxyPutResponse,
    ProxyPutResponseParams,
)
from spacepackets.countdown import Countdown
from spacepackets.seqcount import SeqCountProvider
from spacepackets.util import ByteFieldU8

from ..protocols.edl_command import (
    EdlCommandCode,
    EdlCommandError,
    EdlCommandRequest,
    EdlCommandResponse,
)
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError, EdlVcid
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time
from .beacon import BeaconService
from .node_manager import NodeManagerService
from .radios import RadiosService


class EdlService(Service):
    """'EDL Service"""

    def __init__(
        self,
        node: MasterNode,
        radios_service: RadiosService,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
    ):
        super().__init__()

        self._radios_service = radios_service
        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service

        upload_dir = f"{node.work_base_dir}/upload"
        self._file_receiver = EdlFileReciever(upload_dir, node.fwrite_cache)

        # objs
        edl_rec = node.od["edl"]
        tx_rec = node.od["tx_control"]
        self._flight_mode_obj = node.od["flight_mode"]
        self._seq_num = edl_rec["sequence_count"].value
        self._tx_enable_obj = tx_rec["enable"]
        self._last_tx_enable_obj = tx_rec["last_enable_timestamp"]
        self._edl_sequence_count_obj = edl_rec["sequence_count"]
        self._edl_rejected_count_obj = edl_rec["rejected_count"]
        self._last_edl_obj = edl_rec["last_timestamp"]

    @property
    def _hmac_key(self) -> bytes:
        edl_rec = self.node.od["edl"]
        active_key = edl_rec["active_crypto_key"].value
        return edl_rec[f"crypto_key_{active_key}"].value

    @property
    def _flight_mode(self) -> bool:
        return bool(self._flight_mode_obj.value)

    @property
    def _sequence_count(self) -> int:
        return self._edl_sequence_count_obj.value

    @_sequence_count.setter
    def _sequence_count(self, value):
        self._edl_sequence_count_obj.value = value

    @property
    def _rejected_count(self) -> int:
        return self._edl_rejected_count_obj.value

    @_rejected_count.setter
    def _rejected_count(self, value):
        self._edl_rejected_count_obj.value = value

    def _upack_last_recv(self) -> Optional[EdlPacket]:
        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return None

        try:
            packet = EdlPacket.unpack(message, self._hmac_key, not self._flight_mode)
        except EdlPacketError as e:
            self._rejected_count += 1
            self._rejected_count &= 0xFF_FF_FF_FF
            logger.error(f"invalid EDL request packet: {e}")
            return None  # no responses to invalid packets

        if self._flight_mode and packet.seq_num < self._sequence_count:
            logger.error(
                f"invalid EDL request packet sequence number of {packet.seq_num}, should be > "
                f"{self._sequence_count}"
            )
            return None  # no responses to invalid packets

        self._last_edl_obj.value = int(time())

        if self._flight_mode:
            self._sequence_count = packet.seq_num
            self._sequence_count &= 0xFF_FF_FF_FF

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
                self._tx_enable_obj.value = False
                self._last_tx_enable_obj.value = 0
                ret = False
            else:
                logger.info("EDL enabling Tx")
                self._tx_enable_obj.value = True
                self._last_tx_enable_obj.value = int(time())
                ret = True
        elif request.code == EdlCommandCode.C3_SOFT_RESET:
            logger.info("EDL soft reset")
            self.node.stop(NodeStop.SOFT_RESET)
        elif request.code == EdlCommandCode.C3_HARD_RESET:
            logger.info("EDL hard reset")
            self.node.stop(NodeStop.HARD_RESET)
        elif request.code == EdlCommandCode.C3_FACTORY_RESET:
            logger.info("EDL factory reset")
            self.node.stop(NodeStop.FACTORY_RESET)
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
            ret = (ecode, len(data), data)

        if ret is not None and not isinstance(ret, tuple):
            ret = (ret,)  # make ret a tuple

        response = EdlCommandResponse(request.code, ret)

        logger.info(f"EDL command response: {response.code.name}, values: {response.values}")

        return response


class PrefixedFilestore(HostFilestore):
    """A HostFilestore modified to only run in a specified directory"""

    def __init__(self, prefix: Path):
        if not prefix.is_dir():
            raise NotADirectoryError("prefix must be a directory")
        self._prefix = prefix

    def read_data(self, file: Path, offset: Optional[int], read_len: Optional[int] = None) -> bytes:
        return super().read_data(self._prefix.joinpath(file), offset, read_len)

    def file_exists(self, path: Path) -> bool:
        return super().file_exists(self._prefix.joinpath(path))

    def is_directory(self, path: Path) -> bool:
        return super().is_directory(self._prefix.joinpath(path))

    def truncate_file(self, file: Path):
        super().truncate_file(self._prefix.joinpath(file))

    def write_data(self, file: Path, data: bytes, offset: Optional[int]):
        super().write_data(self._prefix.joinpath(file), data, offset)

    def create_file(self, file: Path) -> FilestoreResponseStatusCode:
        return super().create_file(self._prefix.joinpath(file))

    def delete_file(self, file: Path) -> FilestoreResponseStatusCode:
        return super().delete_file(self._prefix.joinpath(file))

    def rename_file(self, old_file: Path, new_file: Path) -> FilestoreResponseStatusCode:
        return super().rename_file(self._prefix.joinpath(old_file), self._prefix.joinpath(new_file))

    def replace_file(self, replaced_file: Path, source_file: Path) -> FilestoreResponseStatusCode:
        return super().replace_file(
            self._prefix.joinpath(replaced_file),
            self._prefix.joinpath(source_file),
        )

    def remove_directory(
        self, dir_name: Path, recursive: bool = False
    ) -> FilestoreResponseStatusCode:
        return super().remove_directory(self._prefix.joinpath(dir_name), recursive)

    def create_directory(self, dir_name: Path) -> FilestoreResponseStatusCode:
        return super().create_directory(self._prefix.joinpath(dir_name))

    def list_directory(
        self, dir_name: Path, target_file: Path, recursive: bool = False
    ) -> FilestoreResponseStatusCode:
        return super().list_directory(self._prefix.joinpath(dir_name), target_file, recursive)


class VfsCrcHelper(CrcHelper):
    """CrcHelper but modified to only use Filestore operations.

    It previously would attempt to open the paths passed to it directly instead of asking the
    filestore, which failed when using the above PrefixFilestore.
    """

    def calc_modular_checksum(self, file_path: Path) -> bytes:
        """Calculates the modular checksum of the file in file_path.

        This was a module level function in cfdppy but it accessed the filesystem directly
        instead of going through a filestore. It needs to become a CrcHelper method to use the
        provided filestore.
        """
        checksum = 0
        offset = 0
        while True:
            data = self.vfs.read_data(file_path, offset, 4)
            offset += 4
            if not data:
                break
            checksum += int.from_bytes(data.ljust(4, b"\0"), byteorder="big", signed=False)

        checksum %= 2**32
        return struct.pack("!I", checksum)

    def calc_for_file(self, file_path: Path, file_sz: int, segment_len: int = 4096) -> bytes:
        if self.checksum_type == ChecksumType.NULL_CHECKSUM:
            return NULL_CHECKSUM_U32
        if self.checksum_type == ChecksumType.MODULAR:
            return self.calc_modular_checksum(file_path)
        crc_obj = self.generate_crc_calculator()
        if segment_len == 0:
            raise ValueError("Segment length can not be 0")
        if not self.vfs.file_exists(file_path):
            raise SourceFileDoesNotExist(file_path)
        current_offset = 0

        # Calculate the file CRC
        while current_offset < file_sz:
            if current_offset + segment_len > file_sz:
                read_len = file_sz - current_offset
            else:
                read_len = segment_len
            if read_len > 0:
                crc_obj.update(self.vfs.read_data(file_path, current_offset, read_len))
            current_offset += read_len
        return crc_obj.digest()


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

    def __init__(self, upload_dir: str, fwrite_cache: OreSatFileCache):
        path = Path(upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        super().__init__(vfs=PrefixedFilestore(path))

        SOURCE_ID = ByteFieldU8(0)
        DEST_ID = ByteFieldU8(1)

        localcfg = LocalEntityCfg(
            local_entity_id=DEST_ID,
            indication_cfg=IndicationCfg(),
            default_fault_handlers=LogFaults(),
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

        self.fwrite_cache = fwrite_cache
        self.dest = DestHandler(
            cfg=localcfg,
            user=self,
            remote_cfg_table=remote_entities,
            check_timer_provider=DefaultCheckTimer(),
        )
        self.dest._cksum_verif_helper = VfsCrcHelper(ChecksumType.NULL_CHECKSUM, self.vfs)

        self.source = SourceHandler(
            cfg=localcfg,
            user=self,
            remote_cfg_table=remote_entities,
            check_timer_provider=DefaultCheckTimer(),
            seq_num_provider=SeqCountProvider(16),
        )

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
                except FsmNotCalledAfterPacketInsertion:
                    # Usually this exception means the library is being used wrong, so we have
                    # to be careful here. However there is a bug in the presence of dropped packets
                    # where dest._params.last_inserted_packet does not get cleared.
                    logger.exception("dest.state_machine() didn't properly clear inserted packet")
                    self.dest.reset()
            else:
                try:
                    self.source.insert_packet(pdu)
                except FsmNotCalledAfterPacketInsertion:
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

        self.dest.state_machine()
        self.source.state_machine()

        pdus = []
        while self.dest.packets_ready:
            pdus.append(self.dest.get_next_packet().pdu)
        while self.source.packets_ready:
            pdus.append(self.source.get_next_packet().pdu)

        for out in pdus:
            logger.info(f"---> {out}")
        return pdus or None

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
            put = PutRequest(
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
            self.scheduled_requests.put(put)
            del self.active_requests[params.transaction_id]

    def metadata_recv_indication(self, params: MetadataRecvParams):
        logger.info(f"Indication: Metadata Recv. {params}")
        for msg in params.msgs_to_user or []:
            if msg.is_reserved_cfdp_message():
                reserved = msg.to_reserved_msg_tlv()
                if reserved.is_cfdp_proxy_operation():
                    proxyparams = reserved.get_proxy_put_request_params()
                    put = PutRequest(
                        destination_id=proxyparams.dest_entity_id,
                        source_file=Path(proxyparams.source_file_as_path),
                        dest_file=Path(proxyparams.dest_file_as_path),
                        trans_mode=None,
                        closure_requested=None,
                        msgs_to_user=[
                            OriginatingTransactionId(
                                params.transaction_id
                            ).to_generic_msg_to_user_tlv()
                        ],
                    )
                    self.scheduled_requests.put(put)

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
