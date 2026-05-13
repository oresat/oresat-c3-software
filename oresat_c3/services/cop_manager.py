from typing import Optional, Tuple

from olaf import Service, logger

from ..protocols.cop1 import CopService, ServiceInterface
from ..protocols.cop1.farm import Farm1, FarmHigherServiceInterface
from ..protocols.edl_packet import EdlVcid


class CopManagerService(Service):
    """COP-1 Services Manager"""

    def __init__(self):
        super().__init__()
        self._services: dict[EdlVcid, CopService] = {}

    def on_loop(self) -> None:
        for srv in self._services.values():
            srv.tick()

    def create_service(self, vcid: EdlVcid) -> Tuple[ServiceInterface, FarmHigherServiceInterface]:
        logger.info(f"Creating Cop Service for VCID {vcid}")
        srv = Farm1(w=20, vcf_count_length=2)
        self._services[vcid] = srv
        return srv.lower_interface, srv.higher_interface

    def get_service(self, vcid: EdlVcid) -> Optional[CopService]:
        return self._services.get(vcid)
