from .abc_cmd import AbcCmd, logger


class RxTestCmd(AbcCmd):
    id = 18
    req_format = None
    res_format = None

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("")
