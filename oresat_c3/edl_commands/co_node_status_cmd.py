from .abc_cmd import AbcCmd, logger


class CoNodeStatusCmd(AbcCmd):
    id = 5
    req_format = "B"
    res_format = "B"

    def run(self, request: tuple) -> tuple:
        (node_id,) = request
        name = self.node_mngr.node_id_to_name[node_id]
        logger.info(f"EDL getting CANopen node {name} (0x{node_id:02X}) status")
        ret = self.node.node_status[name]

        return (ret,)
