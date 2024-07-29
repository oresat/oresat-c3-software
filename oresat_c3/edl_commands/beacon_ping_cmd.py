from .abc_cmd import AbcCmd, logger
from ..services import BeaconService


class BeaconPingCmd(AbcCmd):
    id = 16
    req_format = None
    res_format = None

    def __init__(
        beacon_service: BeaconService,
    ):
        super().__init__()  # ?

    def run(self, request: tuple) -> tuple:
        logger.info("EDL beacon")
        self.beacon_service.send()  # ?
