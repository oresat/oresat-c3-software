# Tx control

# use struct to figure out bytes

import time

from .abc_cmd import AbcCmd, logger, struct


class TxCtrlCmd(AbcCmd):
    id = ""
    req_format = "?"
    res_format = "?"

    def __init__(self, node, node_mngr):
        super().__init__(node, node_mngr)
        self._tx_enable_obj = node.od["tx_control"]["enable"]
        self._last_tx_enable_obj = node.od["tx_control"]["last_enable_timestamp"]

    def run(self, request: bytes) -> bytes:
        (enable,) = struct.unpack(self.req_format, request)
        if not enable:
            logger.info("EDL disabling Tx")
            self._tx_enable_obj.value = False
            self._last_tx_enable_obj.value = 0
            ret = False
        else:
            logger.info("EDL enabling Tx")
            self._tx_enable_obj.value = True
            self._last_tx_enable_obj.value = int(time())
            ret = True

        return struct.pack(self.res_format, ret)
