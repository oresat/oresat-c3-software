from .abc_cmd import AbcCmd, logger


class PingCmd(AbcCmd):
    id = 17
    req_format = "I"
    res_format = "I"

    def run(self, request: tuple) -> tuple:
        logger.info("EDL ping")
        return request
