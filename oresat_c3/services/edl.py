"""'EDL Service"""

import zlib
from enum import IntEnum, auto
from pathlib import Path
from time import monotonic, time
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

from ..edl_commands import (
    TxCtrlCmd,
    C3SoftResetCmd,
    C3HardResetCmd,
    C3FactoryResetCmd,
    CoNodeEnableCmd,
    CoNodeStatusCmd,
    CoSdoWriteCmd,
    CoSyncCmd,
    OpdSysEnableCmd,
    OpdScanCmd,
    OpdProbeCmd,
    OpdEnableCmd,
    OpdResetCmd,
    OpdStatusCmd,
    RtcSetTimeCmd,
    TimeSyncCmd,
    BeaconPingCmd,
    PingCmd,
    RxTestCmd,
    CoSdoReadCmd,
)
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

    edl_commands = {
        EdlCommandCode.TX_CTRL: TxCtrlCmd,
        EdlCommandCode.C3_SOFT_RESET: C3SoftResetCmd,
        EdlCommandCode.C3_HARD_RESET: C3HardResetCmd,
        EdlCommandCode.C3_FACTORY_RESET: C3FactoryResetCmd,
        EdlCommandCode.CO_NODE_ENABLE: CoNodeEnableCmd,
        EdlCommandCode.CO_NODE_STATUS: CoNodeStatusCmd,
        EdlCommandCode.CO_SDO_WRITE: CoSdoWriteCmd,
        EdlCommandCode.CO_SYNC: CoSyncCmd,
        EdlCommandCode.OPD_SYSENABLE: OpdSysEnableCmd,
        EdlCommandCode.OPD_SCAN: OpdScanCmd,
        EdlCommandCode.OPD_PROBE: OpdProbeCmd,
        EdlCommandCode.OPD_ENABLE: OpdEnableCmd,
        EdlCommandCode.OPD_RESET: OpdResetCmd,
        EdlCommandCode.OPD_STATUS: OpdStatusCmd,
        EdlCommandCode.RTC_SET_TIME: RtcSetTimeCmd,
        EdlCommandCode.TIME_SYNC: TimeSyncCmd,
        EdlCommandCode.BEACON_PING: BeaconPingCmd,
        EdlCommandCode.PING: PingCmd,
        EdlCommandCode.RX_TEST: RxTestCmd,
        EdlCommandCode.CO_SDO_READ: CoSdoReadCmd,
    }

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
        self._node = node

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
                f"invalid EDL request packet sequence number of {req_packet.seq_num}, should be > "
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

        edl_cmd = self.edl_commands[request.code]
        edl_command = edl_cmd(self._node, self._node_mgr_service)
        ret = edl_command.run(request.args)

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
        pdu = NakPdu(
            start_of_scope=self.last_nak,
            end_of_scope=self.offset,
            pdu_conf=self.PDU_CONF,
        )
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

        if monotonic() > self.last_pdu_ts + 10 and self.last_indication != Indication.NONE:
            self.reset()
            return None

        if req_pdu:
            self.last_pdu_ts = monotonic()

        if self.last_indication == Indication.NONE:
            if isinstance(req_pdu, MetadataPdu):
                self._init_recv(req_pdu)
                self.last_indication = Indication.METADATA_RECV
            elif req_pdu is not None and not isinstance(req_pdu, AckPdu):
                res_pdu = self._make_nak(req_pdu)
        elif self.last_indication in [
            Indication.METADATA_RECV,
            Indication.FILE_SEGMENT_RECV,
        ]:
            if isinstance(req_pdu, FileDataPdu):
                res_pdu = self._recv_data(req_pdu)
                self.last_indication = Indication.FILE_SEGMENT_RECV
            elif isinstance(req_pdu, EofPdu) and self.offset >= self.file_data_len:
                res_pdu = self._eof(req_pdu)
                self.last_indication = Indication.EOF_RECV
            elif req_pdu is not None and not isinstance(req_pdu, MetadataPdu):
                res_pdu = self._make_nak(req_pdu)
        elif self.last_indication in [
            Indication.EOF_RECV,
            Indication.TRANSACTION_FINISHED,
        ]:
            if self.last_pdu_ts > monotonic() + 10:
                self.reset()
            elif isinstance(req_pdu, EofPdu):
                res_pdu = self._eof(req_pdu)
                self.last_indication = Indication.EOF_RECV
                self.send_fin_ts = monotonic() + self.FIN_DELAY_S
            elif isinstance(req_pdu, AckPdu):
                logger.info("fin ack!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                self.last_indication = Indication.TRANSACTION_FINISHED
                if req_pdu.directive_code_of_acked_pdu == DirectiveType.FINISHED_PDU:
                    self.reset()
                self.send_fin_ts = monotonic() + self.FIN_DELAY_S
            elif self.send_fin_ts != 0.0 and self.send_fin_ts > monotonic():
                res_pdu = FinishedPdu(
                    pdu_conf=self.PDU_CONF, params=FinishedParams.success_params()
                )
                self.last_indication = Indication.TRANSACTION_FINISHED

        if res_pdu is not None:
            logger.debug(self.last_indication.name)
        return res_pdu
