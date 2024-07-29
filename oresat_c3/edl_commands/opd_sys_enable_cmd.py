from .abc_cmd import AbcCmd, logger


class OpdSysEnableCmd(AbcCmd):
    id = 8
    req_format = "?"
    res_format = "?"

    def run(self, request: tuple) -> tuple:
        (enable,) = request
        if enable:
            logger.info("EDL enabling OPD subsystem")
            self.node_mngr.opd.enable()
        else:
            logger.info("EDL disabling OPD subsystem")
            self.node_mngr.opd.disable()

        (ret,) = self.node_mngr.opd.status.value
        return ret
