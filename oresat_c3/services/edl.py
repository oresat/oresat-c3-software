"""'EDL Service"""

import zlib
from enum import IntEnum, auto
from pathlib import Path
from time import time
from typing import Any, Union

import canopen
from olaf import MasterNode, NodeStop, OreSatFileCache, Service, logger
from spacepackets.cfdp import ConditionCode, CrcFlag, LargeFileFlag, TransmissionMode
from spacepackets.cfdp.conf import PduConfig
from spacepackets.cfdp.defs import Direction
from spacepackets.cfdp.pdu import (
    AbstractFileDirectiveBase,
    AckPdu,
    DirectiveType,
    EofPdu,
    FinishedParams,
    FinishedPdu,
    MetadataPdu,
    NakPdu,
    TransactionStatus,
)
from spacepackets.cfdp.pdu.file_data import FileDataPdu
from spacepackets.util import ByteFieldU8

from ..protocols.edl_command import (
    EdlCommandCode,
    EdlCommandError,
    EdlCommandRequest,
    EdlCommandResponse,
)
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError, EdlVcid
from .beacon import BeaconService
from .node_manager import NodeManagerService
from .radios import RadiosService


class Indication(IntEnum):
    """CFDP Indications."""

    NONE = 0  # not an actually Indication, just a flag
    TRANSACTION = auto()
    EOF_SENT = auto()
    TRANSACTION_FINISHED = auto()
    METADATA_RECV = auto()
    FILE_SEGMENT_RECV = auto()
    REPORT = auto()
    SUSPENDED = auto()
    RESUMED = auto()
    FAULT = auto()
    ABANDONED = auto()
    EOF_RECV = auto()


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

    def _get_hmac_key(self) -> bytes:
        """GEt the active HMAC key."""

        edl_rec = self.node.od["edl"]
        active_key = edl_rec["active_crypto_key"].value
        return edl_rec[f"crypto_key_{active_key}"].value

    def _upack_last_recv(self) -> Union[EdlPacket, None]:
        req_packet = None

        if len(self._radios_service.recv_queue) == 0:
            return req_packet

        req_message = self._radios_service.recv_queue.pop()

        try:
            req_packet = EdlPacket.unpack(
                req_message, self._get_hmac_key(), not self._flight_mode_obj.value
            )
        except Exception as e:  # pylint: disable=W0718
            self._edl_rejected_count_obj.value += 1
            self._edl_rejected_count_obj.value &= 0xFF_FF_FF_FF
            logger.error(f"invalid EDL request packet: {e}")
            return None  # no responses to invalid packets

        if self._flight_mode_obj.value and req_packet.seq_num < self._edl_sequence_count_obj.value:
            logger.error(
                f"invalid EDL request packet sequence number of {req_packet.seq_num}, shoudl be > "
                f"{self._edl_sequence_count_obj.value}"
            )
            return None  # no responses to invalid packets

        self._last_edl_obj.value = int(time())

        if self._flight_mode_obj.value:
            self._edl_sequence_count_obj.value = req_packet.seq_num
            self._edl_sequence_count_obj.value &= 0xFF_FF_FF_FF

        return req_packet

    def on_loop(self):
        req_packet = self._upack_last_recv()

        if req_packet is None and self._file_receiver.last_indication == Indication.NONE:
            self.sleep_ms(50)
            return

        if req_packet is not None and req_packet.vcid == EdlVcid.C3_COMMAND:
            try:
                res_payload = self._run_cmd(req_packet.payload)
                if not res_payload.values:
                    return  # no response
            except Exception as e:  # pylint: disable=W0718
                logger.error(f"EDL command {req_packet.payload.code.name} raised: {e}")
                return
        elif req_packet is None:
            # hardcode to only asume upload for now!!!
            res_payload = self._file_receiver.loop(None)
        elif req_packet.vcid == EdlVcid.FILE_TRANSFER:
            # hardcode to only asume upload for now!!!
            res_payload = self._file_receiver.loop(req_packet.payload)
        else:
            logger.error(f"got an EDL packet with unknown VCID: {req_packet.vcid}")
            return

        if res_payload is None:
            return

        try:
            res_packet = EdlPacket(
                res_payload, self._edl_sequence_count_obj.value, SRC_DEST_UNICLOGS
            )
            res_message = res_packet.pack(self._get_hmac_key())
        except (EdlCommandError, EdlPacketError, ValueError) as e:
            logger.error(f"EDL response generation raised: {e}")
            return

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
            logger.info(f"EDL setting the RTC to {request.args[0]}")
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


class EdlFileReciever:
    """CFDP receiver for file uploads."""

    PDU_CONF = PduConfig(
        transaction_seq_num=ByteFieldU8(0),
        trans_mode=TransmissionMode.ACKNOWLEDGED,
        source_entity_id=ByteFieldU8(0),
        dest_entity_id=ByteFieldU8(0),
        file_flag=LargeFileFlag.NORMAL,
        crc_flag=CrcFlag.NO_CRC,
        direction=Direction.TOWARDS_RECEIVER,
    )

    FIN_DELAY_S = 0.5

    def __init__(self, upload_dir: str, fwrite_cache: OreSatFileCache):
        self.upload_dir = upload_dir
        Path(upload_dir).mkdir(parents=True, exist_ok=True)
        self.fwrite_cache = fwrite_cache
        self.file_name = ""
        self.file_data = b""
        self.file_data_len = 0
        self.f = None
        self.offset = 0
        self.last_nak = 0
        self.last_indication = Indication.NONE
        self.last_pdu_ts = 0.0
        self.send_fin_ts = 0.0
        self.checksum_matched = False

    def reset(self):
        """Reset the EDL file receiver."""

        logger.info("reset")
        if self.f is not None:
            self.f.close()
            self.f = None
        self.offset = 0
        self.last_nak = 0
        self.file_name = ""
        self.file_data = b""
        self.file_data_len = 0
        self.last_indication = Indication.NONE
        self.checksum_matched = False

    def _init_recv(self, pdu: MetadataPdu):
        if self.f is None:
            self.reset()
            self.file_name = pdu.dest_file_name
            self.file_data_len = pdu.file_size
            logger.info(f"{self.file_name} {self.file_data_len} started")
            self.f = open(f"{self.upload_dir}/{self.file_name}", "wb")  # type: ignore

    def _recv_data(self, pdu: FileDataPdu) -> Union[NakPdu, None]:
        if pdu.offset != self.offset:
            return self._make_nak(pdu)

        self.f.write(pdu.file_data)  # type: ignore
        self.offset += len(pdu.file_data)
        self.file_data += pdu.file_data
        if self.offset >= self.file_data_len:
            logger.info("file transfer done")

        logger.info(f"{self.last_indication.name} {self.offset} write")
        return None

    def _eof(self, pdu: EofPdu) -> AckPdu:
        condition_code = ConditionCode.NO_ERROR
        checksum = zlib.crc32(self.file_data).to_bytes(4, "little")
        if checksum == pdu.file_checksum:
            condition_code = ConditionCode.FILE_CHECKSUM_FAILURE
            logger.info("file checksum matched")
            self.checksum_matched = True
        else:
            logger.info("file checksum does not match")

        if self.f is not None and self.checksum_matched:
            self.f.close()
            self.f = None
            try:
                self.fwrite_cache.add(f"{self.upload_dir}/{self.file_name}", consume=True)
                logger.info(f"file {self.file_name} moved to fwrite cache")
            except (ValueError, FileNotFoundError) as e:
                logger.error(e)
            logger.info(f"{self.file_name} {self.file_data_len} ended")

        ack_pdu = AckPdu(
            directive_code_of_acked_pdu=DirectiveType.EOF_PDU,
            condition_code_of_acked_pdu=condition_code,
            transaction_status=TransactionStatus.TERMINATED,
            pdu_conf=self.PDU_CONF,
        )
        logger.info("eof ack")
        return ack_pdu

    def _make_nak(self, recv_pdu):
        pdu = NakPdu(start_of_scope=self.last_nak, end_of_scope=self.offset, pdu_conf=self.PDU_CONF)
        self.last_nak = self.offset
        logger.info(
            f"{self.last_indication.name} {self.offset} nak to {recv_pdu.__class__.__name__}"
        )
        return pdu

    def loop(self, req_pdu: AbstractFileDirectiveBase) -> AbstractFileDirectiveBase:
        """
        The receiver entity loop.

        Parameters
        ----------
        req_message: AbstractFileDirectiveBase, None
            The last received PDU or None

        Returns
        -------
        list[AbstractFileDireciveBase]
            List of PDUs to send to sender entity or an empty list.
        """

        res_pdu = None

        if req_pdu is None and self.last_indication == Indication.NONE:
            return None  # nothing to do

        if time() > self.last_pdu_ts + 10 and self.last_indication != Indication.NONE:
            self.reset()
            return None

        if req_pdu:
            self.last_pdu_ts = time()

        if self.last_indication == Indication.NONE:
            if isinstance(req_pdu, MetadataPdu):
                self._init_recv(req_pdu)
                self.last_indication = Indication.METADATA_RECV
            elif req_pdu is not None and not isinstance(req_pdu, AckPdu):
                res_pdu = self._make_nak(req_pdu)
        elif self.last_indication in [Indication.METADATA_RECV, Indication.FILE_SEGMENT_RECV]:
            if isinstance(req_pdu, FileDataPdu):
                res_pdu = self._recv_data(req_pdu)
                self.last_indication = Indication.FILE_SEGMENT_RECV
            elif isinstance(req_pdu, EofPdu) and self.offset >= self.file_data_len:
                res_pdu = self._eof(req_pdu)
                self.last_indication = Indication.EOF_RECV
            elif req_pdu is not None and not isinstance(req_pdu, MetadataPdu):
                res_pdu = self._make_nak(req_pdu)
        elif self.last_indication in [Indication.EOF_RECV, Indication.TRANSACTION_FINISHED]:
            if self.last_pdu_ts > time() + 10:
                self.reset()
            elif isinstance(req_pdu, EofPdu):
                res_pdu = self._eof(req_pdu)
                self.last_indication = Indication.EOF_RECV
                self.send_fin_ts = time() + self.FIN_DELAY_S
            elif isinstance(req_pdu, AckPdu):
                logger.info("fin ack!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                self.last_indication = Indication.TRANSACTION_FINISHED
                if req_pdu.directive_code_of_acked_pdu == DirectiveType.FINISHED_PDU:
                    self.reset()
                self.send_fin_ts = time() + self.FIN_DELAY_S
            elif self.send_fin_ts != 0.0 and self.send_fin_ts > time():
                res_pdu = FinishedPdu(
                    pdu_conf=self.PDU_CONF, params=FinishedParams.success_params()
                )
                self.last_indication = Indication.TRANSACTION_FINISHED

        if res_pdu is not None:
            logger.debug(self.last_indication.name)
        return res_pdu
