from queue import Empty, Full, Queue, SimpleQueue

from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.edl_packet import EdlVcid
from ..protocols.uslp import unpack_frame
from .radios import RadiosService


class ChannelRouterService(Service):
    """Virtual Channel Router Service

    The router handles fetching raw data from the radios, unpacking frames, and finally places
    valid frames into the appropriate queue.
    """

    QUEUE_SIZE = 256

    def __init__(self, radios_service: RadiosService):
        super().__init__()
        self._radios_service = radios_service
        self._uplink_routes: dict[EdlVcid, Queue[TransferFrame]] = {}
        self._downlink_routes: dict[EdlVcid, SimpleQueue[TransferFrame]] = {}

    def on_loop(self) -> None:
        for dl in self._downlink_routes.values():
            try:
                msg = dl.get_nowait()
                self._radios_service.send_edl_response(msg)
            except Empty:
                continue

        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return

        try:
            frame = unpack_frame(message)
            vcid = frame.header.vcid
            if vcid in self._uplink_routes:
                try:
                    self._uplink_routes[vcid].put_nowait(frame)
                except Full:
                    logger.warning(f"{vcid} queue full: frame discarded")
            else:
                logger.error(f"No route for VCID {frame.header.vcid}")

        except Exception as e:
            logger.exception(f"Failed to unpack frame: {e}")

    def request_uplink_route(self, vcid: EdlVcid) -> Queue[TransferFrame]:
        if vcid in self._uplink_routes:
            return self._uplink_routes[vcid]
        else:
            q = Queue(ChannelRouterService.QUEUE_SIZE)
            self._uplink_routes[vcid] = q
            return q

    def request_downlink_route(self, vcid: EdlVcid) -> SimpleQueue[bytes]:
        if vcid in self._downlink_routes:
            return self._downlink_routes[vcid]
        else:
            q = SimpleQueue()
            self._downlink_routes[vcid] = q
            logger.info(f"Created downlink route for VCID {vcid}")
            return q
