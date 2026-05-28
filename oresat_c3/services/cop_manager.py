from queue import Empty, Queue
from typing import Optional

from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.cop1 import CopService, Gvcid
from ..protocols.cop1.farm import (
    Farm1,
    FarmHigherServiceInterface,
    FduArrivedIndication,
    ValidFrameArrivedIndication,
)
from ..protocols.edl_packet import EdlVcid


class CopManagerService(Service):
    """COP-1 Services Manager

    This service acts as both the Higher and Lower procedures for any number of FARM-1
    or FOP-1 COP-1 services
    """

    def __init__(self) -> None:
        super().__init__()
        self._services: dict[EdlVcid, tuple[CopService, Queue]] = {}
        self.recv_queue: Queue[TransferFrame] = Queue()

    def on_loop(self) -> None:
        self._process_farm_lower()
        self._process_farm_higher()

    def _process_farm_lower(self) -> None:
        try:
            frame = self.recv_queue.get_nowait()
            srv, q = self._services.get(frame.header.vcid, None)
            print(srv)
            if srv is not None:
                if srv.lower_interface.buffer.appendleft(frame):
                    srv.lower_interface.signal.appendleft(
                        ValidFrameArrivedIndication(
                            Gvcid(0b1100, frame.header.scid, frame.header.vcid)
                        )
                    )
                    srv.tick()
                else:
                    logger.warning(f"FARM VCID={frame.header.vcid}: buffer full")
        except Empty:
            pass

    def _process_farm_higher(self) -> None:
        for srv, q in self._services.values():
            hi: FarmHigherServiceInterface = srv.higher_interface
            try:
                sig = hi.signal.pop()
                if isinstance(sig, FduArrivedIndication):
                    # TODO: FDU Arrived should actually queue the frame and notify the USER (EDL)
                    #  with a notif primitive that the frame is in the queue
                    q.put_nowait(hi.buffer.pop())
                    hi.buffer_release.set()
            except IndexError:
                continue

    def create_service(self, vcid: EdlVcid) -> Queue:
        logger.info(f"Creating Cop Service for VCID {vcid}")
        q = Queue()
        self._services[vcid] = (Farm1(w=20, vcf_count_length=2), q)
        return q

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        entry = self._services.get(vcid)
        if entry is not None:
            return entry[0]
        else:
            return entry
