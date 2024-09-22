from .abc_cmd import AbcCmd, logger


class C3FactoryResetCmd(AbcCmd):
    id = 3
    req_format = None
    res_format = None

    def run(self, request: tuple) -> tuple:
        logger.info("EDL factory reset")
        self.node.stop(self.node_mngr.NodeStop.FACTORY_RESET)
