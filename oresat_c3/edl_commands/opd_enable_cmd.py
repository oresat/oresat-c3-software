from .abc_cmd import AbcCmd, logger


class OpdEnableCmd(AbcCmd):
    id = 11
    req_format = "B?"
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        (opd_addr, disable) = request
        name = self.node_mngr.opd_addr_to_name[opd_addr]
        node = self.node_mngr.opd[name]
        if disable:
            logger.info(f"EDL disabling OPD node {name} (0x{opd_addr:02X})")
            ret = node.disable()
        else:
            logger.info(f"EDL enabling OPD node {name} (0x{opd_addr:02X})")
            ret = node.enable()
        ### ?
        ret = node.status.value
