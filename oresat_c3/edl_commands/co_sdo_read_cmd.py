from .abc_cmd import AbcCmd, logger


class CoSdoReadCmd(AbcCmd):
    id = 19
    req_format = "BHB"
    res_format = None

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("")
