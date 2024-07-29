from .abc_cmd import AbcCmd, logger, NodeStop  # ?


class C3SoftResetCmd(AbcCmd):
    id = 1
    req_format = None
    res_format = None

    def run(self, request: tuple) -> tuple:
        logger.info("EDL soft reset")
        self.node.stop(self.node_mngr.NodeStop.SOFT_RESET)
