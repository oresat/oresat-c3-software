import socket
from time import time
from threading import Thread, Event

from olaf import Resource, logger

from ..opd import Opd, OpdNode
from ..edl import EdlServer, EdlError, EdlCode


class EdlResource(Resource):

    _UPLINK_ADDR = ('localhost', 10025)
    _DOWNLINK_ADDR = ('localhost', 10016)
    _BUFFER_LEN = 1024

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        logger.info(f'EDL uplink socket: {self._UPLINK_ADDR}')
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._uplink_socket.bind(self._UPLINK_ADDR)
        self._uplink_socket.settimeout(5)

        logger.info(f'EDL downlink socket: {self._DOWNLINK_ADDR}')
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._edl_server = None
        self._opd = Opd()

        self._event = Event()
        self._thread = Thread(target=self._edl_thread)

    def on_start(self):

        hamc_key = self.od['Crypto Key'].value
        seq_num = self.od['Persistent State']['EDL Sequence Count'].value
        self._edl_server = EdlServer(hamc_key, seq_num)
        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _edl_thread(self):

        while not self._event.is_set():
            try:
                message, sender = self._uplink_socket.recvfrom(self._BUFFER_LEN)
                logger.info(f'EDL recv: {message.hex(sep=" ")}')
            except TimeoutError:
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

        ret = (0).to_bytes(1, 'little')

        if code == EdlCode.TX_CTRL:
            logger.info('enabling OPD system')
            if args == b'\x00':
                self.od['Persistent state']['Last TX Enable'].value = 0
            else:
                self.od['Persistent state']['Last TX Enable'].value = int(time())
        elif code == EdlCode.OPD_SYSENABLE:
            logger.info('enabling OPD system')
            self._opd.start()
        elif code == EdlCode.OPD_SYSDISABLE:
            logger.info('disabling OPD system')
            self._opd.stop()
        elif code == EdlCode.OPD_SCAN:
            node = OpdNode.from_bytes(args[0])
            logger.info(f'scaning for OPD node {node}')
            self._opd.scan(node)
        elif code == EdlCode.OPD_ENABLE:
            node = OpdNode.from_bytes(args[0])
            if args[1] == b'\x00':
                logger.info(f'enabling OPD node {node}')
                self._opd.enable(node)
            else:
                logger.info(f'disabling OPD node {node}')
                self._opd.disable(node)
        elif code == EdlCode.OPD_RESET:
            node = OpdNode.from_bytes(args[0])
            logger.info(f'resetting for OPD node {node}')
            self._opd.reset(node)
        elif code == EdlCode.OPD_STATUS:
            node = OpdNode.from_bytes(args[0])
            logger.info(f'getting the status for OPD node {node}')
            ret = self._opd.status(node).to_bytes()
        elif code == EdlCode.TIME_SYNC:
            logger.info('sending time sync TPDO')
            self.send_tpdo(0)

        # TODO the rest

        return ret
