''''
EDL Service

Handle recing EDL command and sending replys.
'''

import socket
from time import time

import canopen
from olaf import Service, logger, NodeStop

from .. import NodeId
from ..protocols.edl_packet import EdlPacket, EdlPacketError, SRC_DEST_UNICLOGS
from ..protocols.edl_command import EdlCommandCode, EdlCommandPacketError, EdlCommandRequest, EdlCommandResponse
from ..subsystems.opd import Opd, OpdNode


class EdlService(Service):

    _UPLINK_ADDR = ('localhost', 10025)
    _DOWNLINK_ADDR = ('localhost', 10016)
    _BUFFER_LEN = 1024

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd

        logger.info(f'EDL uplink socket: {self._UPLINK_ADDR}')
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._uplink_socket.bind(self._UPLINK_ADDR)
        self._uplink_socket.settimeout(1)

        logger.info(f'EDL downlink socket: {self._DOWNLINK_ADDR}')
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def on_start(self):

        self._hmac_key = self.node.od['Crypto Key'].value
        self._seq_num = self.node.od['Persistent State']['EDL Sequence Count'].value

        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']
        persist_state_rec = self.node.od['Persistent State']
        self._last_tx_enabled_obj = persist_state_rec['Last TX Enable']
        self._edl_sequence_count_obj = persist_state_rec['EDL Sequence Count']
        self._edl_rejected_count_obj = persist_state_rec['EDL Rejected Count']
        self._last_edl_obj = persist_state_rec['Last EDL']

    def on_loop(self):

        try:
            req_message, _ = self._uplink_socket.recvfrom(self._BUFFER_LEN)
        except socket.timeout:
            return

        logger.info(f'EDL request packet: {req_message.hex(sep=" ")}')

        if len(req_message) == 0:
            return  # no message

        try:
            req_packet = EdlPacket.unpack(self._hmac_key, req_message)
        except (EdlCommandPacketError, EdlPacketError) as e:
            self._edl_rejected_count_obj.value += 1
            self._edl_rejected_count_obj.value &= 0xFF_FF_FF_FF
            logger.error(f'invalid EDL request packet: {e}')
            return

        self._last_edl_obj.value = int(time())
        self._edl_sequence_count_obj.value += 1
        self._edl_sequence_count_obj.value &= 0xFF_FF_FF_FF

        try:
            res_payload = self._run_cmd(req_packet.payload)
        except Exception as e:
            logger.error(f'EDL command {req_packet.payload.code.name} raised: {e}')
            return

        try:
            res_peacket = EdlPacket(res_payload, self._edl_sequence_count_obj.value, SRC_DEST_UNICLOGS)
            res_message = res_peacket.pack(self._hmac_key)
        except (EdlCommandPacketError, EdlPacketError) as e:
            logger.error(f'EDL response generation raised: {e}')
            return

        logger.info(f'EDL response packet: {res_message.hex(sep=" ")}')

        try:
            self._downlink_socket.sendto(res_message, self._DOWNLINK_ADDR)
        except Exception as e:
            logger.error(f'failed to send EDL response: {e}')

    def _run_cmd(self, request: EdlCommandRequest) -> EdlCommandResponse:

        ret = None

        logger.info(f'EDL command response: {request.code.name}, args: {request.args}')

        if request.code == EdlCommandCode.TX_CTRL:
            if request.args[0]:
                logger.info('EDL enabling Tx')
                self._tx_enabled_obj.value = True
                self._last_tx_enabled_obj.value = int(time())
                ret = True
            else:
                logger.info('EDL disabling Tx')
                self._tx_enabled_obj.value = False
                self._last_tx_enabled_obj.value = 0
                ret = False
        elif request.code == EdlCommandCode.C3_SOFT_RESET:
            logger.info('EDL soft reset')
            self.node.stop(NodeStop.SOFT_RESET)
        elif request.code == EdlCommandCode.C3_HARD_RESET:
            logger.info('EDL hard reset')
            self.node.stop(NodeStop.HARD_RESET)
        elif request.code == EdlCommandCode.C3_FACTORY_RESET:
            logger.info('EDL factory reset')
            self.node.stop(NodeStop.FACTORY_RESET)
        elif request.code == EdlCommandCode.CO_NODE_ENABLE:
            node = NodeId(request.args[0])
            logger.info(f'EDL enabling CANopen node {node.name}')
            # TODO
            ret = 5 # Temp, must return an int
        elif request.code == EdlCommandCode.CO_NODE_STATUS:
            node = NodeId(request.args[0])
            logger.info(f'EDL getting CANopen node {node.name} status')
            ret = self.node.node_status[node.value][0]
        elif request.code == EdlCommandCode.CO_SDO_WRITE:
            node_id, index, subindex, size, data = request.args
            node = NodeId(node_id)
            logger.info(f'EDL SDO write on CANopen node {node.name}')
            try:
                self.sdo_write(node_id, index, subindex, data)
                ret = 0
            except canopen.SdoError as e:
                logger.error(e)
                e_str = str(e)
                ret = int(e_str[-10:], 16)  # last 10 chars is always the sdo error code in hex
        elif request.code == EdlCommandCode.CO_SYNC:
            logger.info('EDL sending CANopen SYNC message')
            self.node.send_sync()
            ret = True
        elif request.code == EdlCommandCode.OPD_SYSENABLE:
            enable = OpdNode.from_bytes(request.args[0])
            if enable:
                logger.info('EDL enabling OPD subsystem')
                self._opd.enable()
            else:
                logger.info('EDL disabling OPD subsystem')
                self._opd.disable()
            ret = self._opd.is_system_enabled
        elif request.code == EdlCommandCode.OPD_SCAN:
            logger.info('EDL scaning for all OPD nodes')
            ret = self._opd.scan()
        elif request.code == EdlCommandCode.OPD_PROBE:
            node = OpdNode.from_bytes(request.args[0])
            logger.info(f'EDL probing for OPD node {node.name}')
            ret = self._opd[node].probe()
        elif request.code == EdlCommandCode.OPD_ENABLE:
            node = OpdNode.from_bytes(request.args[0])
            if request.args[1] == b'\x00':
                logger.info(f'EDL disabling OPD node {node_id.name}')
                ret = self._opd[node_id].disable()
            else:
                logger.info(f'EDL enabling OPD node {node.name}')
                ret = self._opd[node_id].enable()
            ret = self._opd[node].status.value
        elif request.code == EdlCommandCode.OPD_RESET:
            node = OpdNode.from_bytes(request.args[0])
            logger.info(f'EDL resetting for OPD node {node.name}')
            self._opd[node].reset
            ret = self._opd[node].status.value
        elif request.code == EdlCommandCode.OPD_STATUS:
            node = OpdNode.from_bytes(request.args[0])
            logger.info(f'EDL getting the status for OPD node {node.name}')
            ret = self._opd[node].status.value
        elif request.code == EdlCommandCode.RTC_SET_TIME:
            logger.info(f'EDL setting the RTC to {request.args[0]}')
            # TODO
        elif request.code == EdlCommandCode.TIME_SYNC:
            logger.info('EDL sending time sync TPDO')
            self.node.send_tpdo(0)

        if type(ret) not in [None, tuple]:
            ret = ret,  # make ret a tuple

        response = EdlCommandResponse(request.code, ret)

        logger.info(f'EDL command response: {response.code.name}, values: {response.values}')

        return response
