from .abc_cmd import AbcCmd, logger


class OpdProbeCmd(AbcCmd):
    id = 10
    req_format = "B"
    res_format = "?"

    def run(self, request: tuple) -> tuple:
        (opd_addr,) = request
        name = self.node_mngr.opd_addr_to_name[opd_addr]
        logger.info(f"EDL probing for OPD node {name} (0x{opd_addr:02X})")
        (ret,) = self.node_mngr.opd[name].probe()
        return ret
