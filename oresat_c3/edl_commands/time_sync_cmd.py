from .abc_cmd import AbcCmd, logger


class TimeSyncCmd(AbcCmd):
    id = 15
    req_format = None
    res_format = "?"

    def run(self, request: tuple) -> tuple:
        logger.info("EDL sending time sync TPDO")
        self.node.send_tpdo(0)
