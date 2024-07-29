from .abc_cmd import AbcCmd, logger


class CoSdoReadCmd(AbcCmd):
    id = 19
    req_format = "BHB"
    res_format = None

    def run(self, request: tuple) -> tuple:
        logger.info("")
