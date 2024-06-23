from .abc_cmd import AbcCmd, logger, struct


class OpdResetCmd(AbcCmd):
    id = 12
    req_format = "B"
    res_format = "B"

    def __init(self, node, node_mngr):
        self.node = node
        self.node_mngr = node_mngr

    def run(self, request: bytes) -> bytes:
        (opd_addr,) = struct.unpack(self.req_format, request)
        name = self._node_mngr.opd_addr_to_name[opd_addr]
        logger.info(f"EDL resetting OPD node {name} (0x{opd_addr:02X})")
        node = self._node_mngr.opd[name]
        node.reset()
        ret = node.status.value
        response = struct.pack(self.res_format, ret)
        return response
