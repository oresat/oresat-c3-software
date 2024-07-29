from .abc_cmd import AbcCmd, logger


class OpdStatusCmd(AbcCmd):
    id = 13
    req_format = "B"
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        (opd_addr,) = request
        name = self.node_mngr.opd_addr_to_name[opd_addr]
        logger.info(f"EDL getting the status for OPD node {name} (0x{opd_addr:02X})")
        (ret,) = self.node_mngr.opd[name].status.value
        return ret
