from queue import SimpleQueue
from typing import Optional, Tuple

from olaf import Service, logger
from spacepackets.uslp import TransferFrame

from ..protocols.cop1 import CopService, Farm1
from ..protocols.edl_packet import EdlVcid


class CopManagerService(Service):
    """COP-1 Services Manager"""

    def __init__(self):
        super().__init__()
        self._services: dict[EdlVcid, CopService] = {}

    def on_loop(self) -> None:
        for srv in self._services.values():
            srv.tick()

    def create_service(
        self, vcid: EdlVcid
    ) -> Tuple[SimpleQueue[TransferFrame], SimpleQueue[TransferFrame]]:
        logger.info(f"Creating Cop Service for VCID {vcid}")
        srv = Farm1(w=254, vcf_count_length=2)
        self._services[vcid] = srv
        return srv.lower_buffer, srv.higher_buffer

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        return self._services.get(vcid)
