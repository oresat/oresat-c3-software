from .abc_cmd import AbcCmd, logger


class OpdScanCmd(AbcCmd):
    id = 9
    req_format = None
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        logger.info("EDL scaning for all OPD nodes")
        (ret,) = self.node_mngr.opd.scan()
        return ret
