from .abc_cmd import AbcCmd, logger


class TimeSyncCmd(AbcCmd):
    id = 15
    req_format = None
    res_format = "?"

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("")
