from queue import Empty, Full, Queue

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
        self._routes: dict[EdlVcid, Queue[TransferFrame]] = {}

    def on_loop(self) -> None:
        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return

        try:
            frame = unpack_frame(message)
            vcid = frame.header.vcid
            if vcid in self._routes:
                try:
                    self._routes[vcid].put_nowait(frame)
                except Full:
                    logger.warning(f"{vcid} queue full: frame discarded")
            else:
                logger.error(f"No route for VCID {frame.header.vcid}")

        except Exception as e:
            logger.exception(f"Failed to unpack frame: {e}")

    def request_route(self, vcid: EdlVcid) -> Queue[TransferFrame]:
        if vcid in self._routes:
            raise KeyError(f"Route already exists: {vcid}")
        q: Queue[TransferFrame] = Queue(ChannelRouterService.QUEUE_SIZE)
        self._routes[vcid] = q
        return q
