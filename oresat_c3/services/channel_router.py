from queue import Empty, Full, Queue

from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.cop1 import ControlWord, Farm1
from ..protocols.edl_packet import EdlVcid
from ..protocols.uslp import Gvcid, unpack_frame
from .cop_manager import CopManagerService
from .radios import RadiosService


class ChannelRouterService(Service):
    """Virtual Channel Router Service

    The router handles fetching raw data from the radios, unpacking frames, and finally places
    valid frames into the appropriate queue.
    """

    QUEUE_SIZE = 256

    def __init__(self, radios_service: RadiosService, cop_service: CopManagerService):
        super().__init__()
        self._radios_service = radios_service
        self._cop_service = cop_service
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
                    logger.info("routing packet")
                    self._routes[vcid].put_nowait(frame)
                except Full:
                    logger.warning(f"{vcid} queue full: frame discarded")
                cop = self._cop_service.get_service(vcid)
                if cop is not None:
                    logger.info("VCID has COP")
                    cop.notify(
                        Farm1.ValidFrameArrivedIndication(
                            Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                        )
                    )
            else:
                logger.error(f"No route for VCID {frame.header.vcid}")

        except Exception as e:
            logger.exception(f"Failed to unpack frame: {e}")

    def request_route(self, vcid: EdlVcid, cop: bool = False) -> Queue[TransferFrame]:
        """Request the creation of a route from the radios.

        Parameters
        ----------
        vcid : EdlVcid
            The Virtual Channel Identifier for this channel route. Only one route can exist per VCID.
        cop : bool
            Enable the COP-1 service on this channel. Currently only supports FARM-1 (receive).

        Returns
        -------
        Queue[TransferFrame]
            A Queue acting as a buffer through which all valid USLP Transfer Frames exit the route.

        Raises
        ------
        KeyError
            The route already exists for the given VCID.

        """

        if vcid in self._routes:
            raise KeyError(f"Route already exists: {vcid}")
        out_queue: Queue[TransferFrame]
        if cop:
            low_buf, out_queue = self._cop_service.create_service(vcid)
            self._routes[vcid] = low_buf
        else:
            out_queue = Queue(ChannelRouterService.QUEUE_SIZE)
            self._routes[vcid] = out_queue
        logger.info(f"Created route for VCID {vcid}, cop={cop}")
        return out_queue

    def get_control_word(self, vcid: EdlVcid) -> ControlWord:
        service = self._cop_service.get_service(vcid)
        if service is None or not isinstance(service, Farm1):
            raise ValueError(f"VCID {vcid} is not FARM-1")
        service: Farm1 = service
        return ControlWord(
            vcid=vcid,
            lockout=service.lockout,
            wait=service.wait,
            retransmit=service.retransmit,
            farm_b_counter=service.b_counter,
            report_value=service.receiver_frame_sequence_number,
        )
