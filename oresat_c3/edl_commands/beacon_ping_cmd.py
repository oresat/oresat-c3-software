from .abc_cmd import AbcCmd, logger


class BeaconPingCmd(AbcCmd):
    id = 16
    req_format = None
    res_format = None

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("EDL beacon")
        self._beacon_service.send()
