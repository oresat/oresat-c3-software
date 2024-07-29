from .abc_cmd import AbcCmd, logger


class CoSyncCmd(AbcCmd):
    id = 7
    req_format = None
    res_format = "?"

    def run(self, request: tuple) -> tuple:
        logger.info("EDL sending CANopen SYNC message")
        self.node.send_sync()
