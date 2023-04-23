''''
EDL Resource

Handle recing EDL command and sending replys.
'''

import socket
import struct
from time import time
from threading import Thread, Event

import canopen
from olaf import Resource, logger

from .. import NodeId
from ..protocols.edl import EdlServer, EdlError, EdlCode
from ..subsystems.opd import Opd, OpdNode, OpdError, Max7310Error
from ..subsystems.rtc import Rtc
from . import soft_reset, hard_reset, factory_reset


class EdlResource(Resource):

    _UPLINK_ADDR = ('localhost', 10025)
    _DOWNLINK_ADDR = ('localhost', 10016)
    _BUFFER_LEN = 1024

    def __init__(self, opd: Opd, rtc: Rtc):
        super().__init__()

        self.opd = opd
        self.rtc = rtc

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
        self._last_tx_enabled_obj = self.node.od['Persistent State']['Last TX Enable']
        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _edl_thread(self):

        while not self._event.is_set():
            try:
                message, sender = self._uplink_socket.recvfrom(self._BUFFER_LEN)
                logger.info(f'EDL recv: {message.hex(sep=" ")}')
            except (TimeoutError, socket.timeout):
                continue

            if len(message) == 0:
                continue  # Skip empty packets

            try:
                payload = self._edl_server.parse_request(message)
                code = EdlCode.from_bytes(payload[0])
            except EdlError as e:
                logger.error(e)
                continue

            try:
                self._run_cmd(code, payload[1:])
            except Exception as e:
                logger.error(f'EDL command {code} raised: {e}')
                continue

            try:
                response = self._edl_server.generate_response(payload)
            except EdlError as e:
                logger.error(e)
                continue

            self._downlink_socket.sendto(response, self._DOWNLINK_ADDR)
            logger.info(f'EDL sent: {response.hex(sep=" ")}')

    def _run_cmd(self, code: EdlCode, args: bytes) -> bytes:

        ret = 0
        fmt = 'b'

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
                soft_reset()
            elif code == EdlCode.C3_HARDRESET:
                logger.info('EDL hard reset')
                hard_reset()
            elif code == EdlCode.C3_FACTORYRESET:
                logger.info('EDL factory reset')
                factory_reset()
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
                enable = OpdNode.from_bytes(args[0])
                if enable:
                    logger.info('EDL enabling OPD system')
                    self._opd.start()
                else:
                    logger.info('EDL disabling OPD system')
                    self._opd.stop()
                ret = self._opd.is_system_enabled
            elif code == EdlCode.OPD_SCAN:
                logger.info('EDL scaning for all OPD nodes')
                ret = self._opd.scan()
            elif code == EdlCode.OPD_PROBE:
                fmt = '?'
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL probing for OPD node {node.name}')
                ret = self._opd.probe(node)
            elif code == EdlCode.OPD_ENABLE:
                node = OpdNode.from_bytes(args[0])
                if args[1] == b'\x00':
                    logger.info(f'EDL disabling OPD node {node.name}')
                    self._opd.disable_node(node)
                else:
                    logger.info(f'EDL enabling OPD node {node.name}')
                    self._opd.enable_node(node)
                ret = self._opd.node_status(node).value
            elif code == EdlCode.OPD_RESET:
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL resetting for OPD node {node.name}')
                self._opd.reset_node(node)
                ret = self._opd.node_status(node).value
            elif code == EdlCode.OPD_STATUS:
                node = OpdNode.from_bytes(args[0])
                logger.info(f'EDL getting the status for OPD node {node.name}')
                ret = self._opd.node_status(node).value
            elif code == EdlCode.RTC_SET_TIME:
                fmt = 'I'
                value = struct.unpack(fmt, args)
                logger.info(f'EDL setting the RTC {value}')
                self.rtc.set_time(value)
            elif code == EdlCode.TIME_SYNC:
                logger.info('EDL sending time sync TPDO')
                self.node.send_tpdo(0)
        except (Max7310Error, OpdError) as e:  # an OPD command failed
            logger.error(f'EDL error {e}')
            ret = 0

        return struct.pack(fmt, ret)
