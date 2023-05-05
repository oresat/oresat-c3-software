''''
OPD (OreSat Power Domain) Resource

Handle powering OreSat cards on and off.
'''

import json
from time import time

from olaf import Resource, TimerLoop

from ..subsystems.opd import Opd, OpdNode, OpdNodeState
from .. import NodeId


OPD_NODE_TO_CO_NODE = {
    OpdNode.BATTERY_0: NodeId.BATTERY_0,
    OpdNode.GPS: NodeId.GPS,
    OpdNode.ACS: NodeId.ACS,
    OpdNode.DXWIFI: NodeId.DXWIFI,
    OpdNode.STAR_TRACKER_0: NodeId.STAR_TRACKER_0,
    OpdNode.BATTERY_1: NodeId.BATTERY_1,
    OpdNode.CFC: NodeId.CFC,
    # CFC_SENSOR is not a CANopen node
    OpdNode.RW_0: NodeId.RW_0,
    OpdNode.RW_1: NodeId.RW_1,
    OpdNode.RW_2: NodeId.RW_2,
    OpdNode.RW_3: NodeId.RW_3,
}


class OpdResource(Resource):

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd
        self.cur_node = list(OpdNode)[0]

    def on_start(self):

        self.node.od[0x8001][0x2].value = '{}'
        self.node.add_sdo_read_callback(0x8001, self._on_read)
        self.node.add_sdo_write_callback(0x8001, self._on_write)

        self._timer_loop = TimerLoop('OPD monitor', self._loop, 60000)
        self._timer_loop.start()

    def on_end(self):

        self._timer_loop.stop()

    def _on_read(self, index: int, subindex: int):

        value = None

        if subindex == 0x1:
            value = self.opd.is_system_enabled
        elif subindex == 0x2:
            raw = {node.value: self.opd.status(node).value for node in list(OpdNode)}
            value = json.dumps(raw)
        elif subindex == 0x3:
            value = self.cur_node.value
        elif subindex == 0x4:
            value = self.opd.status(self.cur_node).value

        return value

    def _on_write(self, index: int, subindex: int, value):

        if subindex == 0x1:
            if value is True:
                self.opd.start()
            else:
                self.opd.stop()
        elif subindex == 0x3:
            self.cur_node = OpdNode(value)
        elif subindex == 0x4:
            if value == 1:
                self.opd.enable(self.cur_node)
            elif value == 0:
                self.opd.disable(self.cur_node)
        elif subindex == 0x5:
            self.opd.scan(False)

    def _loop(self) -> bool:
        '''Monitor all OPD nodes and check that nodes that are on are sending heartbeats.'''

        self.opd.monitor_nodes()

        if self.opd.is_subsystem_dead:
            return False  # no reason to continue to loop

        for node in list(OpdNode):
            if node == OpdNode.CFC_SENSOR:
                continue  # not a CANopen node

            co_node = OPD_NODE_TO_CO_NODE[node]
            co_status = self.node.node_status[co_node.value]
            if self.opd.status(node) == OpdNodeState.ON and co_status[1] + 60 < time():
                # card is on, but no CANopen heartbeat have been received in a minute, reset it
                self.opd.reset(node)

        return True
