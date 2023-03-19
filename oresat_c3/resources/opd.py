''''
OPD (OreSat Power Domain) Resource
==================================

Mostly for testing.

Handle turnin card on and off and keeps track of cards.
'''

import json

from olaf import Resource

from ..opd import Opd, OpdNode


class OpdResource(Resource):

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd
        self.cur_node = list(OpdNode)[0]

    def on_start(self):

        self.node.od[0x8001][0x2].value = '{}'
        self.node.add_sdo_read_callback(0x8001, self._on_read)
        self.node.add_sdo_write_callback(0x8001, self._on_write)

    def _on_read(self, index: int, subindex: int):

        if subindex == 0x1:
            value = self.opd.is_system_enabled
        elif subindex == 0x2:
            raw = {node.value: self.opd.node_status(node) for node in list(OpdNode)}
            value = json.dumps(raw)
        elif subindex == 0x3:
            value = self.cur_node.value
        elif subindex == 0x4:
            value = self.opd.node_status(self.cur_node)

        return value

    def _on_write(self, index: int, subindex: int, value):

        if subindex == 0x1:
            if value is True:
                self.opd.enable_system()
            else:
                self.opd.disable_system()
        elif subindex == 0x3:
            self.cur_node = OpdNode(value)
        elif subindex == 0x4:
            if value is True:
                self.opd.enable_node(self.cur_node)
            else:
                self.opd.disable_node(self.cur_node)
