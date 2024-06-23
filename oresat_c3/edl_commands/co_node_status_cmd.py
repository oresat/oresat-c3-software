from .abc_cmd import AbcCmd, logger, struct


class CoNodeStatusCmd(AbcCmd):
    id = 5
    req_format = "B"
    res_format = "B"

    def run(self, request: bytes) -> bytes:
        (node_id,) = struct.unpack(self.req_format, request)
        name = self._node_mgr_service.node_id_to_name[node_id]
        logger.info(f"EDL getting CANopen node {name} (0x{node_id:02X}) status")
        ret = self.node.node_status[name]

        return struct.pack(self.res_format, ret)
