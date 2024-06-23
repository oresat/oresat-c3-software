from .abc_cmd import AbcCmd, logger


class RtcSetTimeCmd(AbcCmd):
    id = 14
    req_format = "I"
    res_format = "?"

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("")
