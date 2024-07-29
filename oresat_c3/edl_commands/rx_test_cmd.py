from .abc_cmd import AbcCmd, logger


class RxTestCmd(AbcCmd):
    id = 18
    req_format = None
    res_format = None

    def run(self, request: tuple) -> tuple:
        logger.info("EDL Rx test")
