''''
EDL Resource

Handle recing EDL command and sending replys.
'''

import socket
import struct
from time import time
from threading import Thread, Event

import canopen
from olaf import Resource, logger, NodeStop

from .. import NodeId
from ..protocols.edl import EdlServer, EdlError, EdlCode
from ..subsystems.opd import Opd, OpdNodeId, OpdError, Max7310Error


class EdlResource(Resource):

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

        self._event = Event()
        self._thread = Thread(target=self._edl_thread)

    def on_start(self):

        hmac_key = self.node.od['Crypto Key'].value
        seq_num = self.node.od['Persistent State']['EDL Sequence Count'].value
        self._edl_server = EdlServer(hmac_key, seq_num)

        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']
        persist_state_rec = self.node.od['Persistent State']
        self._last_tx_enabled_obj = persist_state_rec['Last TX Enable']
        self._edl_sequence_count_obj = persist_state_rec['EDL Sequence Count']
        self._edl_rejected_count_obj = persist_state_rec['EDL Rejected Count']
        self._last_edl_obj = persist_state_rec['Last EDL']

        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _edl_thread(self):

        while not self._event.is_set():
            try:
                message, sender = self._uplink_socket.recvfrom(self._BUFFER_LEN)
                logger.info(f'EDL request packet: {message.hex(sep=" ")}')
            except socket.timeout:
                continue

            if len(message) == 0:
                continue  # Skip empty packets

            try:
                payload = self._edl_server.parse_request(message)
                code = EdlCode.from_bytes(payload[0])
            except EdlError as e:
                self._edl_rejected_count_obj.value += 1
                logger.error(f'Invalid EDL request packet: {e}')
                continue

            self._last_edl_obj.value = int(time())
            self._edl_sequence_count_obj.value += 1

            try:
                self._run_cmd(code, payload[1:])
            except Exception as e:
                logger.error(f'EDL command {code.name} raised: {e}')
                continue

            try:
                response = self._edl_server.generate_response(payload)
            except EdlError as e:
                logger.error(f'EDL response generation raised: {e}')
                continue

            self._downlink_socket.sendto(response, self._DOWNLINK_ADDR)
            logger.info(f'EDL response packet: {response.hex(sep=" ")}')

    def _run_cmd(self, code: EdlCode, args: bytes) -> bytes:

        ret = 0
        fmt = 'B'

        args_hex = args.hex(sep=' ')
        logger.info(f'running EDL command: 0x{code:02X}, arg(s): {args_hex}')

        try:
            if code == EdlCode.TX_CTRL:
                if args == b'\x00':
                    logger.info('EDL disabling Tx')
                    self._tx_enabled_obj.value = False
                else:
                    logger.info('EDL enabling Tx')
                    self._tx_enabled_obj.value = True
                    self._last_tx_enabled_obj.value = int(time())
                    ret = 1
            elif code == EdlCode.C3_SOFTRESET:
                logger.info('EDL soft reset')
                self.node.stop(NodeStop.SOFT_RESET)
            elif code == EdlCode.C3_HARDRESET:
                logger.info('EDL hard reset')
                self.node.stop(NodeStop.HARD_RESET)
            elif code == EdlCode.C3_FACTORYRESET:
                logger.info('EDL factory reset')
                self.node.stop(NodeStop.FACTORY_RESET)
            elif code == EdlCode.CO_NODE_ENABLE:
                node = NodeId.from_bytes(args[0])
                logger.info(f'EDL enabling CANopen node {node.name}')
                # TODO
            elif code == EdlCode.CO_NODE_STATUS:
                node = NodeId.from_bytes(args[0])
                logger.info(f'EDL getting CANopen node {node.name} status')
                ret = self.node.node_status[node.value]
            elif code == EdlCode.CO_SDO_WRITE:
                fmt = 'I'
                node_id, index, subindex, size = struct.unpack('<2BHI', args[:8])
                data = args[8:]
                node = NodeId(node_id)
                logger.info(f'EDL SDO write on CANopen node {node.name}')
                try:
                    self.sdo_write(node_id, index, subindex, data)
                    ret = 0
                except canopen.SdoError as e:
                    logger.error(e)
                    # last 10 chars are always the sdo error code in hex
                    ret = int(str(e)[-10:], 16)
            elif code == EdlCode.CO_SYNC:
                logger.info('EDL sending CANopen SYNC message')
                self.node.send_sync()
            elif code == EdlCode.OPD_SYSENABLE:
                fmt = '?'
                if bool(int(args[0])):
                    logger.info('EDL enabling OPD subsystem')
                    self._opd.start()
                else:
                    logger.info('EDL disabling OPD subsystem')
                    self._opd.stop()
                ret = self._opd.is_system_enabled
            elif code == EdlCode.OPD_SCAN:
                logger.info('EDL scaning for all OPD nodes')
                ret = self._opd.scan()
            elif code == EdlCode.OPD_PROBE:
                fmt = '?'
                node_id = OpdNodeId.from_bytes(args[0])
                logger.info(f'EDL probing for OPD node {node_id.name}')
                ret = self._opd[node_id].probe()
            elif code == EdlCode.OPD_ENABLE:
                node = OpdNodeId.from_bytes(args[0])
                if args[1] == b'\x00':
                    logger.info(f'EDL disabling OPD node {node_id.name}')
                    self._opd[node_id].disable()
                else:
                    logger.info(f'EDL enabling OPD node {node_id.name}')
                    self._opd[node_id].enable()
                ret = self._opd[node_id].status
            elif code == EdlCode.OPD_RESET:
                node_id = OpdNodeId.from_bytes(args[0])
                logger.info(f'EDL resetting for OPD node {node_id.name}')
                self._opd[node_id].reset()
                ret = self._opd[node_id].status
            elif code == EdlCode.OPD_STATUS:
                node_id = OpdNodeId.from_bytes(args[0])
                logger.info(f'EDL getting the status for OPD node {node_id.name}')
                ret = self._opd[node_id].status
            elif code == EdlCode.RTC_SET_TIME:
                fmt = 'I'
                value = struct.unpack(fmt, args)
                logger.info(f'EDL setting the RTC {value}')
                # TODO
            elif code == EdlCode.TIME_SYNC:
                logger.info('EDL sending time sync TPDO')
                self.node.send_tpdo(0)
        except (Max7310Error, OpdError) as e:  # an OPD command failed
            logger.error(f'EDL error {e}')
            ret = 0

        return struct.pack(fmt, ret)
