from .abc_cmd import AbcCmd, logger, NodeStop  # ?


class C3HardResetCmd(AbcCmd):
    id = 2
    req_format = None
    res_format = None

    def run(self, request: tuple) -> tuple:
        logger.info("EDL hard reset")
        self.node.stop(self.node_mngr.NodeStop.HARD_RESET)
