from .abc_cmd import AbcCmd, logger


class OpdEnableCmd(AbcCmd):
    id = 11
    req_format = "B?"
    res_format = "B"

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        logger.info("")
