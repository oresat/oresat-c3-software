from .abc_cmd import AbcCmd, logger, struct


class C3SoftResetCmd(AbcCmd):
    id = 1
    req_format = None
    res_format = None

    def __init__(self, node, node_mngr):
        self.node = node

    def run(self, request: bytes) -> bytes:
        (enable,) = struct.unpack(self.req_format, request)

        logger.info("EDL soft reset")
        self.node.stop(self.node_mngr.NodeStop.SOFT_RESET)

        return struct.pack(self.res_format, enable)
