from .abc_cmd import AbcCmd, logger


class OpdResetCmd(AbcCmd):
    id = 12
    req_format = "B"
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        (opd_addr,) = request
        name = self.node_mngr.opd_addr_to_name[opd_addr]
        logger.info(f"EDL resetting OPD node {name} (0x{opd_addr:02X})")
        node = self.node_mngr.opd[name]
        node.reset()
        (ret,) = node.status.value
        return ret
