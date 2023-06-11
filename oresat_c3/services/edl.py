''''
EDL Service

Handle recing EDL command and sending replys.
'''

import socket
from time import time

import canopen
from olaf import Service, logger, NodeStop

from .. import NodeId
from ..protocols.edl_packet import EdlPacket, EdlPacketError, SRC_DEST_ORESAT
from ..protocols.edl_command import EdlCommandCode
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
            message, sender = self._uplink_socket.recvfrom(self._BUFFER_LEN)
            logger.info(f'EDL request packet: {message.hex(sep=" ")}')
        except socket.timeout:
            return

        if len(message) == 0:
            return  # no message

        try:
            payload = self._edl_server.parse_request(message)
            code = EdlCode.from_bytes(payload[0])
        except EdlError as e:
            self._edl_rejected_count_obj.value += 1
            logger.error(f'Invalid EDL request packet: {e}')
            return

        self._last_edl_obj.value = int(time())
        self._edl_sequence_count_obj.value += 1

        try:
            self._run_cmd(code, payload[1:])
        except Exception as e:
            logger.error(f'EDL command {code.name} raised: {e}')
            return

        try:
            payload = self._edl_server.unpack_request(message)
            code = EdlCode.from_bytes(payload[0])
            payload = payload
        except EdlError as e:
            self._edl_rejected_count_obj.value += 1
            self._edl_rejected_count_obj.value &= 0xFF_FF_FF_FF
            logger.error(f'Invalid EDL request packet: {e}')
            return

        self._last_edl_obj.value = int(time())
        self._edl_sequence_count_obj.value += 1
        self._edl_sequence_count_obj.value &= 0xFF_FF_FF_FF

        try:
            self._run_cmd(code, payload[1:])
        except Exception as e:
            logger.error(f'EDL command {code.name} raised: {e}')
            return

        try:
            response = self._edl_server.pack_response(payload)
        except EdlError as e:
            logger.error(f'EDL response generation raised: {e}')
            return

        self._downlink_socket.sendto(response, self._DOWNLINK_ADDR)
        logger.info(f'EDL response packet: {response.hex(sep=" ")}')

    def _run_cmd(self, code: EdlCommandCode, args: tuple) -> tuple:

        ret = None

        logger.info(f'running EDL command: {code.name}, args: {args}')

        try:
            if code == EdlCommandCode.TX_CTRL:
                if args[0] == b'\x00':
                    logger.info('EDL disabling Tx')
                    self._tx_enabled_obj.value = False
                    self._last_tx_enabled_obj.value = 0
                    ret = False
                else:
                    logger.info('EDL enabling Tx')
                    self._tx_enabled_obj.value = True
                    self._last_tx_enabled_obj.value = int(time())
                    ret = True
            elif code == EdlCommandCode.C3_SOFTRESET:
                logger.info('EDL soft reset')
                self.node.stop(NodeStop.SOFT_RESET)
            elif code == EdlCommandCode.C3_HARDRESET:
                logger.info('EDL hard reset')
                self.node.stop(NodeStop.HARD_RESET)
            elif code == EdlCommandCode.C3_FACTORYRESET:
                logger.info('EDL factory reset')
                self.node.stop(NodeStop.FACTORY_RESET)
            elif code == EdlCommandCode.CO_NODE_ENABLE:
                node = NodeId.from_bytes(args[0])
                logger.info(f'EDL enabling CANopen node {node.name}')
                # TODO
            elif code == EdlCommandCode.CO_NODE_STATUS:
                node = NodeId.from_bytes(args[0])
                logger.info(f'EDL getting CANopen node {node.name} status')
                ret = self.node.node_status[node.value]
            elif code == EdlCommandCode.CO_SDO_WRITE:
                node_id, index, subindex, size, data = args
                node = NodeId(node_id)
                logger.info(f'EDL SDO write on CANopen node {node.name}')
                try:
                    self.sdo_write(node_id, index, subindex, data)
                    ret = 0
                except canopen.SdoError as e:
                    logger.error(e)
                    e_str = str(e)
                    ret = int(e_str[-10:], 16)  # last 10 chars is always the sdo error code in hex
            elif code == EdlCommandCode.CO_SYNC:
                logger.info('EDL sending CANopen SYNC message')
                self.node.send_sync()
            elif code == EdlCommandCode.OPD_SYSENABLE:
                enable = OpdNode.from_bytes(args[0])
                if enable:
                    logger.info('EDL enabling OPD subsystem')
                    self._opd.start()
                else:
                    logger.info('EDL disabling OPD subsystem')
                    self._opd.disable()
                ret = self._opd.is_system_enabled
            elif code == EdlCommandCode.OPD_SCAN:
                logger.info('EDL scaning for all OPD nodes')
                ret = self._opd.scan()
            elif code == EdlCommandCode.OPD_PROBE:
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL probing for OPD node {node.name}')
                ret = self._opd.probe(node)
            elif code == EdlCommandCode.OPD_ENABLE:
                node = OpdNode.from_bytes(args[0])
                if args[1] == b'\x00':
                    logger.info(f'EDL disabling OPD node {node_id.name}')
                    ret = self._opd[node_id].disable()
                else:
                    logger.info(f'EDL enabling OPD node {node.name}')
                    self._opd.enable_node(node)
                ret = self._opd.node_status(node).value
            elif code == EdlCommandCode.OPD_RESET:
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL resetting for OPD node {node.name}')
                self._opd.reset_node(node)
                ret = self._opd.node_status(node).value
            elif code == EdlCommandCode.OPD_STATUS:
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL getting the status for OPD node {node.name}')
                ret = self._opd.node_status(node).value
            elif code == EdlCommandCode.RTC_SET_TIME:
                logger.info(f'EDL setting the RTC to {args[0]}')
                # TODO
            elif code == EdlCommandCode.TIME_SYNC:
                logger.info('EDL sending time sync TPDO')
                self.node.send_tpdo(0)
        except Exception as e:
            logger.exception(f'EDL error: {e}')
            ret = None

        if type(ret) not in [None, tuple]:
            ret = ret,  # make ret a tuple

        return ret
