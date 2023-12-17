"""'EDL Service"""

from time import time
from typing import Any

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId

from ..protocols.edl_command import (
    EdlCommandCode,
    EdlCommandError,
    EdlCommandRequest,
    EdlCommandResponse,
)
from ..protocols.edl_packet import SRC_DEST_UNICLOGS, EdlPacket, EdlPacketError
from .beacon import BeaconService
from .node_manager import NodeManagerService
from .radios import RadiosService


class EdlService(Service):
    """'EDL Service"""

    def __init__(
        self,
        radios_service: RadiosService,
        node_mgr_service: NodeManagerService,
        beacon_service: BeaconService,
    ):
        super().__init__()

        self._radios_service = radios_service
        self._node_mgr_service = node_mgr_service
        self._beacon_service = beacon_service

        self._hmac_key = b""
        self._seq_num = 0

        self._flight_mode_obj: canopen.objectdictionary.Variable = None
        self._tx_enable_obj: canopen.objectdictionary.Variable = None
        self._last_tx_enable_obj: canopen.objectdictionary.Variable = None
        self._edl_sequence_count_obj: canopen.objectdictionary.Variable = None
        self._edl_rejected_count_obj: canopen.objectdictionary.Variable = None
        self._last_edl_obj: canopen.objectdictionary.Variable = None

    def on_start(self):
        edl_rec = self.node.od["edl"]
        tx_rec = self.node.od["tx_control"]

        self._flight_mode_obj = self.node.od["flight_mode"]

        active_key = edl_rec["active_crypto_key"].value
        self._hmac_key = edl_rec[f"crypto_key_{active_key}"].value
        self._seq_num = edl_rec["sequence_count"].value

        self._tx_enable_obj = tx_rec["enable"]
        self._last_tx_enable_obj = tx_rec["last_enable_timestamp"]
        self._edl_sequence_count_obj = edl_rec["sequence_count"]
        self._edl_rejected_count_obj = edl_rec["rejected_count"]
        self._last_edl_obj = edl_rec["last_timestamp"]

    def on_loop(self):
        if len(self._radios_service.recv_queue) == 0:
            self.sleep_ms(500)
            return

        req_message = self._radios_service.recv_queue.pop()

        logger.info(f'EDL request packet: {req_message.hex(sep=" ")}')

        try:
            req_packet = EdlPacket.unpack(req_message, self._hmac_key, self._flight_mode_obj.value)
        except (EdlCommandError, EdlPacketError) as e:
            self._edl_rejected_count_obj.value += 1
            self._edl_rejected_count_obj.value &= 0xFF_FF_FF_FF
            logger.error(f"invalid EDL request packet: {e}")
            return  # no responses to invalid commands

        if req_packet.seq_num < self._edl_rejected_count_obj.value:
            logger.error("invalid EDL request packet sequence number")
            return  # no responses to invalid commands

        self._last_edl_obj.value = int(time())

        if self._flight_mode_obj.value:
            self._edl_sequence_count_obj.value += 1
            self._edl_sequence_count_obj.value &= 0xFF_FF_FF_FF

        try:
            res_payload = self._run_cmd(req_packet.payload)
        except Exception as e:  # pylint: disable=W0718
            logger.error(f"EDL command {req_message.code.name} raised: {e}")
            return

        try:
            res_peacket = EdlPacket(
                res_payload, self._edl_sequence_count_obj.value, SRC_DEST_UNICLOGS
            )
            res_message = res_peacket.pack(self._hmac_key)
        except (EdlCommandError, EdlPacketError) as e:
            logger.error(f"EDL response generation raised: {e}")
            return

        logger.info(f'EDL response packet: {res_message.hex(sep=" ")}')

        self._radios_service.send_edl_response(res_message)

    def _run_cmd(self, request: EdlCommandRequest) -> EdlCommandResponse:
        ret: Any = None

        logger.info(f"EDL command response: {request.code.name}, args: {request.args}")

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
            node = NodeId(int(request.args[0]))
            logger.info(f"EDL enabling CANopen node {node.name}")
        elif request.code == EdlCommandCode.CO_NODE_STATUS:
            node = NodeId(int(request.args[0]))
            logger.info(f"EDL getting CANopen node {node.name} status")
            ret = self.node.node_status[node.value]
        elif request.code == EdlCommandCode.CO_SDO_WRITE:
            node_id, index, subindex, _, data = request.args
            node = NodeId(node_id)
            logger.info(f"EDL SDO write on CANopen node {node.name}")
            try:
                self.node.sdo_write(node_id, index, subindex, data)
                ret = 0
            except canopen.sdo.exceptions.SdoError as e:
                logger.error(e)
                e_str = str(e)
                ret = int(e_str[-10:], 16)  # last 10 chars is always the sdo error code in hex
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
            node_id = request.args[0]
            node = self._node_mgr_service.opd[node_id]
            logger.info(f"EDL probing for OPD node {node_id.name}")
            ret = self._node_mgr_service.opd[node].probe()
        elif request.code == EdlCommandCode.OPD_ENABLE:
            node_id = request.args[0]
            node = self._node_mgr_service.opd[node_id]
            if request.args[1] == b"\x00":
                logger.info(f"EDL disabling OPD node {node_id.name}")
                ret = node.disable()
            else:
                logger.info(f"EDL enabling OPD node {node_id.name}")
                ret = node.enable()
            ret = node.status.value
        elif request.code == EdlCommandCode.OPD_RESET:
            node_id = request.args[0]
            node = self._node_mgr_service.opd[node_id]
            logger.info(f"EDL resetting for OPD node {node_id.name}")
            node.reset()
            ret = node.status.value
        elif request.code == EdlCommandCode.OPD_STATUS:
            node_id = request.args[0]
            node = self._node_mgr_service.opd[node_id]
            logger.info(f"EDL getting the status for OPD node {node.name}")
            ret = self._node_mgr_service.opd[node].status.value
        elif request.code == EdlCommandCode.RTC_SET_TIME:
            logger.info(f"EDL setting the RTC to {request.args[0]}")
        elif request.code == EdlCommandCode.TIME_SYNC:
            logger.info("EDL sending time sync TPDO")
            self.node.send_tpdo(0)
        elif request.code == EdlCommandCode.BEACON_PING:
            self._beacon_service.send()
        elif request.code == EdlCommandCode.PING:
            ret = request.args[0]

        if type(ret) not in [None, tuple]:
            ret = (ret,)  # make ret a tuple

        response = EdlCommandResponse(request.code, ret)

        logger.info(f"EDL command response: {response.code.name}, values: {response.values}")

        return response
