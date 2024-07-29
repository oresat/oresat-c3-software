from .abc_cmd import AbcCmd, logger


class CoNodeEnableCmd(AbcCmd):
    id = 4
    req_format = "B?"
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        (node_id,) = request
        node_name = self.node_mngr.node_id_to_name[node_id]
        logger.info(f"EDL enabling CANopen node {node_name} (0x{node_id:02X})")
