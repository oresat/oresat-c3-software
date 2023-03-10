import socket
from threading import Thread, Event

from olaf import Resource, logger

from ..edl import EdlServer, EdlError


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

        self._event = Event()
        self._thread = Thread(target=self._edl_thread)

    def on_start(self):

        hamc_key = self.od['Crypto Key'].value
        seq_num = self.od['Persistent C3 State']['EDL Sequence Count'].value
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
            except EdlError as e:
                logger.error(e)
                continue

            # TODO run command

            try:
                response = self._edl_server.generate_response(payload)
            except EdlError as e:
                logger.error(e)
                continue

            self._downlink_socket.sendto(response, self._DOWNLINK_ADDR)
            logger.info(f'EDL sent: {response.hex(sep=" ")}')
