from queue import Empty, SimpleQueue
from typing import Optional

from ccsds_cop.cop_1 import CopService, Gvcid
from ccsds_cop.cop_1.farm import (
    Farm1,
    FarmHigherServiceInterface,
    FduArrivedIndication,
    ValidFrameArrivedIndication,
)
from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.edl_packet import EdlVcid


class CopManagerService(Service):
    """COP-1 Services Manager
    This service acts as both the Higher and Lower procedures for any number of FARM-1
    or FOP-1 COP-1 services
    """

    def __init__(self) -> None:
        super().__init__()
        self._farms: dict[EdlVcid, tuple[CopService, SimpleQueue[TransferFrame]]] = {}
        self.recv_queue: SimpleQueue[TransferFrame] = SimpleQueue()

    def on_loop(self) -> None:
        self._process_farm_higher()
        self._process_farm_lower()
        self.sleep_ms(50)

    def _process_farm_lower(self) -> None:
        try:
            frame = self.recv_queue.get_nowait()
            srv, _ = self._farms.get(frame.header.vcid, (None, None))
            if srv is not None:
                if srv.lower_interface.buffer.try_appendleft(frame):
                    srv.lower_interface.signal.try_appendleft(
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
        for srv, q in self._farms.values():
            hi: FarmHigherServiceInterface = srv.higher_interface
            try:
                sig = hi.signal.pop()
                if isinstance(sig, FduArrivedIndication):
                    q.put_nowait(hi.buffer.pop())
                    hi.buffer_release.set()
            except IndexError:
                continue

    def create_farm_service(self, vcid: EdlVcid) -> SimpleQueue[TransferFrame]:
        logger.info(f"Creating FARM-1 Service for VCID {vcid}")
        q: SimpleQueue[TransferFrame] = SimpleQueue()
        self._farms[vcid] = (Farm1(w=20, vcf_count_length=1), q)
        return q

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        entry = self._farms.get(vcid)
        if entry is not None:
            return entry[0]
        else:
            return entry
