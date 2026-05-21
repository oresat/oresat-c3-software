from queue import Empty, Queue, SimpleQueue
from typing import Union

from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.cop1 import ControlWord, Gvcid, ServiceInterface
from ..protocols.cop1.farm import Farm1, FarmHigherServiceInterface, ValidFrameArrivedIndication
from ..protocols.edl_packet import EdlVcid
from ..protocols.uslp import unpack_frame
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
        self._routes: dict[EdlVcid, Union[SimpleQueue[TransferFrame], ServiceInterface]] = {}

    def on_loop(self) -> None:
        try:
            message = self._radios_service.recv_queue.get_nowait()
        except Empty:
            return

        try:
            frame = unpack_frame(message)
            vcid = frame.header.vcid
            if vcid in self._routes:
                route = self._routes[vcid]
                if isinstance(route, ServiceInterface):
                    if route.buffer.appendleft(frame):
                        route.signal.appendleft(
                            ValidFrameArrivedIndication(
                                Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                            )
                        )
                    else:
                        logger.error(f"{vcid} lower queue full: frame discarded")
                else:
                    route.put_nowait(frame)
            else:
                logger.error(f"No route for VCID {frame.header.vcid}")

        except Exception as e:
            logger.exception(f"Failed to unpack frame: {e}")

    def request_route(
        self, vcid: EdlVcid, cop: bool = False
    ) -> Union[SimpleQueue[TransferFrame], FarmHigherServiceInterface]:
        """Request the creation of a route from the radios.

        Parameters
        ----------
        vcid : EdlVcid
            The Virtual Channel Identifier for this channel route. Only one route can exist per VCID.
        cop : bool
            Enable the COP-1 service on this channel. Currently only supports FARM-1 (receive).

        Returns
        -------
        Union[SimpleQueue[TransferFrame], ServiceInterface]
            Access to a Queue through which all valid USLP frames exit the route.
            If `cop` is `False`, frames are directly forwarded to the returned SimpleQueue.
            Otherwise, the COP service's higher ServiceInterface is returned, allowing access to the
            service's buffer and signal queue.

        Raises
        ------
        KeyError
            The route already exists for the given VCID.

        """

        if vcid in self._routes:
            raise KeyError(f"Route already exists: {vcid}")
        if cop:
            low_interface, out = self._cop_service.create_service(vcid)
            self._routes[vcid] = low_interface
        else:
            out: Queue[TransferFrame] = Queue(ChannelRouterService.QUEUE_SIZE)
            self._routes[vcid] = out
        logger.info(f"Created route for VCID {vcid}, cop={cop}")
        return out

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
