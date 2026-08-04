"""'EDL Service"""

from queue import Empty, SimpleQueue
from time import time
from typing import Any, Optional, Union

import canopen
from cfdppy import PacketDestination, get_packet_destination
from cfdppy.mib import (
    RemoteEntityConfig,
    RemoteEntityConfigTable,
)
from olaf import MasterNode, NodeStop, Service, logger
from spacepackets.cfdp import (
    ChecksumType,
    PduHolder,
    TransmissionMode,
)
from spacepackets.cfdp.pdu import AbstractFileDirectiveBase
from spacepackets.uslp import TransferFrame
from spacepackets.util import ByteFieldU8

from ..protocols.cachestore import CacheStore
from ..protocols.cfdp import (
    DestEntityHandler,
    SourceEntityHandler,
)
from ..protocols.edl_command import (
    EdlCommandCode,
    EdlCommandError,
    EdlCommandRequest,
    EdlCommandResponse,
)
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError, EdlVcid
from ..protocols.sdls import SdlsInvalidHmacError
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time
from .beacon import BeaconService
from .channel_router import ChannelRouterService
from .node_flasher import NodeFlasherService
from .node_manager import NodeManagerService


class EdlService(Service):
    """'EDL Service"""

    def __init__(
        self,
        node: MasterNode,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
        channel_router_service: ChannelRouterService,
        node_flasher_service: NodeFlasherService,
    ):
        super().__init__()

        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service
        self._cmd_downlink: SimpleQueue[bytes] = channel_router_service.request_downlink_route(
            EdlVcid.C3_COMMAND
        )
        self._cmd_uplink: SimpleQueue[TransferFrame] = channel_router_service.request_uplink_route(
            EdlVcid.C3_COMMAND,
            use_cop=True,
        )
        self._file_downlink: SimpleQueue[bytes] = channel_router_service.request_downlink_route(
            EdlVcid.FILE_TRANSFER
        )
        self._file_uplink: SimpleQueue[TransferFrame] = channel_router_service.request_uplink_route(
            EdlVcid.FILE_TRANSFER
        )
        self._node_flasher_service = node_flasher_service

        self.put_req_queue = SimpleQueue()  # send new put requests from here
        self._cfdp_tm_queue = SimpleQueue()  # send telemetry pdus from here
        self._cfdp_src_queue = SimpleQueue()  # send tc for the source here
        self._cfdp_dest_queue = SimpleQueue()  # send tc for the dest here
        self._cfdp_source_handler = None
        self._cfdp_dest_handler = None

        self.GND_ID = ByteFieldU8(0)
        self.SAT_ID = ByteFieldU8(1)
        self._init_cfdp(node.fwrite_cache)

        # objs
        edl_rec = node.od["edl"]
        tx_rec = node.od["tx_control"]
        self._flight_mode_obj = node.od["flight_mode"]
        self._seq_num = edl_rec["sequence_count"].value
        self._tx_enable_obj = tx_rec["enable"]
        self._last_tx_enable_obj = tx_rec["last_enable_timestamp"]
        self._edl_sequence_count_obj = edl_rec["sequence_count"]
        self._edl_rejected_count_obj = edl_rec["rejected_count"]
        self._edl_cfdp_seq_count_obj = edl_rec["cfdp_seq_num"]
        self._last_edl_obj = edl_rec["last_timestamp"]

    def on_start(self) -> None:
        self._cfdp_source_handler.set_seq_num(self._edl_cfdp_seq_count_obj.value)
        self.node.add_sdo_callbacks(
            "edl",
            "cfdp_seq_num",
            self._cfdp_source_handler.get_seq_num,
            self._cfdp_source_handler.set_seq_num,
        )

    def __del__(self) -> None:
        # redefinition of the service destructor to handle the cfdp threads
        if not self._event.is_set():
            self._event.set()

        if self._cfdp_source_handler.is_alive():
            self._cfdp_source_handler.join()
        if self._cfdp_dest_handler.is_alive():
            self._cfdp_dest_handler.join()

        if self._thread.is_alive():
            self._thread.join()

    def _init_cfdp(self, fwrite_cache: CacheStore) -> None:
        remote_entities = RemoteEntityConfigTable(
            [
                RemoteEntityConfig(
                    entity_id=self.GND_ID,
                    max_file_segment_len=None,
                    # FIXME this value should come from EdlPacket but EdlPacket does not define it.
                    # How does the exact value get determined? Currently it's just a mirror of the
                    # value in edl_file_upload.py
                    max_packet_len=950,
                    closure_requested=True,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.MODULAR,  # Yamcs only supports the legacy modular crc.
                    immediate_nak_mode=False,
                    nak_timer_interval_seconds=5.0,
                ),
            ]
        )

        self._cfdp_source_handler = SourceEntityHandler(
            self.put_req_queue,
            self._cfdp_src_queue,
            self._cfdp_tm_queue,
            fwrite_cache,
            remote_entities,
            self.GND_ID,
            self.SAT_ID,
            self._event,
        )
        self._cfdp_dest_handler = DestEntityHandler(
            self.put_req_queue,
            self._cfdp_dest_queue,
            self._cfdp_tm_queue,
            fwrite_cache,
            remote_entities,
            self.SAT_ID,
            self._event,
        )
        self._cfdp_source_handler.start()
        self._cfdp_dest_handler.start()

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

    def _frame_to_packet(self, frame: TransferFrame) -> Optional[EdlPacket]:
        try:
            packet = EdlPacket.from_frame(frame, self._hmac_key, not self._flight_mode)
        except (EdlPacketError, SdlsInvalidHmacError) as e:
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

    def _respond(self, vcid: EdlVcid, payload: Union[PduHolder, EdlCommandResponse]) -> None:
        try:
            res_packet = EdlPacket(payload, self._sequence_count, SRC_DEST_UNICLOGS)
            res_message = res_packet.pack(self._hmac_key)
        except (EdlCommandError, EdlPacketError, ValueError) as e:
            logger.exception(f"EDL response generation raised: {e}")
            return

        if vcid == EdlVcid.C3_COMMAND:
            self._cmd_downlink.put_nowait(res_message)
        elif vcid == EdlVcid.FILE_TRANSFER:
            self._file_downlink.put_nowait(res_message)

    def _process_command(self) -> None:
        try:
            frame = self._cmd_uplink.get_nowait()
        except Empty:
            return
        req_packet = self._frame_to_packet(frame)
        if req_packet is not None:
            try:
                res_payload = self._run_cmd(req_packet.payload)
                if not res_payload.values:
                    return  # no response
                self._respond(EdlVcid.C3_COMMAND, res_payload)
            except Exception as e:  # pylint: disable=W0718
                logger.error(f"EDL command {req_packet.payload.code.name} raised: {e}")

    def _process_cfdp(self) -> None:
        try:
            frame = self._file_uplink.get_nowait()
        except Empty:
            frame = None

        if frame is not None:
            req_packet = self._frame_to_packet(frame)
        else:
            req_packet = None

        if req_packet is not None:
            self._handle_pdu(req_packet.payload)

        while not self._cfdp_tm_queue.empty():
            next_tm = self._cfdp_tm_queue.get(False)
            self._respond(EdlVcid.FILE_TRANSFER, next_tm.pdu)

    def _handle_pdu(self, pdu: AbstractFileDirectiveBase):
        packet_dest = get_packet_destination(pdu)
        logger.warning(f"putting cfdp pdu in {packet_dest} queue")
        if packet_dest == PacketDestination.DEST_HANDLER:
            self._cfdp_dest_queue.put(pdu)
        elif packet_dest == PacketDestination.SOURCE_HANDLER:
            self._cfdp_src_queue.put(pdu)
        else:
            logger.error("receieved CFDP pdu intended for unknown destination!")

    def on_loop(self):
        self._process_command()
        self._process_cfdp()
        self.sleep_ms(50)

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
            ret = (node_id, index, subindex, ecode, len(data), data)
        elif request.code == EdlCommandCode.CO_NODE_FLASH:
            node_id, filename, throttle_delay, block_transfer, request_crc, confirm_image = (
                request.args
            )
            logger.info(
                f"EDL queuing node flash for node 0x{node_id:02X} with file {filename} "
                f"(throttle: {throttle_delay}, block: {block_transfer}, "
                f"crc: {request_crc}, confirm: {confirm_image})"
            )
            try:
                self._node_flasher_service.enqueue_flash(
                    node_id,
                    filename,
                    throttle_delay=throttle_delay,
                    block_transfer=block_transfer,
                    request_crc=request_crc,
                    confirm_image=confirm_image,
                )
                ret = True
            except Exception as e:
                logger.error(f"Failed to queue flash: {e}")
                ret = False

        if ret is not None and not isinstance(ret, tuple):
            ret = (ret,)  # make ret a tuple

        response = EdlCommandResponse(request.code, ret)

        logger.info(f"EDL command response: {response.code.name}, values: {response.values}")

        return response
