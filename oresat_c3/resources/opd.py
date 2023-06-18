''''
OPD (OreSat Power Domain) Resource

Handle powering OreSat cards on and off.
'''

import json
from time import time

from olaf import Resource, TimerLoop, logger

from ..subsystems.opd import Opd, OpdNodeId, OpdNodeState
from .. import NodeId


OPD_NODE_TO_CO_NODE = {
    OpdNodeId.BATTERY_0: NodeId.BATTERY_0,
    OpdNodeId.GPS: NodeId.GPS,
    OpdNodeId.ACS: NodeId.ACS,
    OpdNodeId.DXWIFI: NodeId.DXWIFI,
    OpdNodeId.STAR_TRACKER_0: NodeId.STAR_TRACKER_0,
    OpdNodeId.BATTERY_1: NodeId.BATTERY_1,
    OpdNodeId.CFC: NodeId.CFC,
    # CFC_SENSOR is not a CANopen node
    OpdNodeId.RW_0: NodeId.RW_0,
    OpdNodeId.RW_1: NodeId.RW_1,
    OpdNodeId.RW_2: NodeId.RW_2,
    OpdNodeId.RW_3: NodeId.RW_3,
}


class OpdResource(Resource):

    _MAX_CO_RESETS = 3
    _RESET_TIMEOUT_S = 60
    _MONITOR_DELAY_MS = 60_000

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd
        self.cur_node = list(OpdNodeId)[0]
        self._co_resets = {node.id: 0 for node in self.opd}

    def on_start(self):

        self.node.od[0x8001][0x2].value = '{}'
        self.node.add_sdo_read_callback(0x8001, self._on_read)
        self.node.add_sdo_write_callback(0x8001, self._on_write)

        self._timer_loop = TimerLoop('OPD monitor', self._loop, self._MONITOR_DELAY_MS)
        self._timer_loop.start()

    def on_end(self):

        self._timer_loop.stop()

    def _on_read(self, index: int, subindex: int):

        value = None

        if subindex == 0x1:
            value = self.opd.is_subsystem_enabled
        elif subindex == 0x2:
            raw = {node.id.value: node.status.value for node in self.opd}
            value = json.dumps(raw)
        elif subindex == 0x3:
            value = self.cur_node.value
        elif subindex == 0x4:
            value = self.opd[self.cur_node].status.value

        return value

    def _on_write(self, index: int, subindex: int, value):

        if subindex == 0x1:
            if value is True:
                self.opd.enable()
            else:
                self.opd.disable()
        elif subindex == 0x3:
            self.cur_node = OpdNodeId(value)
        elif subindex == 0x4:
            if value == 1:
                self.opd[self.cur_node].enable()
            elif value == 0:
                self.opd[self.cur_node].disable()
        elif subindex == 0x5:
            self.opd.scan(False)

    def _loop(self) -> bool:
        '''Monitor all OPD nodes and check that nodes that are on are sending heartbeats.'''

        self.opd.monitor_nodes()

        if self.opd.is_subsystem_dead:
            return False  # no reason to continue to loop

        for node in self.opd:
            if node.id == OpdNodeId.CFC_SENSOR or node.status == OpdNodeState.DEAD:
                continue  # CFC_SENSOR not a CANopen node or node is dead

            co_node = OPD_NODE_TO_CO_NODE[node.id]
            co_status = self.node.node_status[co_node.value]
            if self._co_resets[node.id] >= self._MAX_CO_RESETS:
                logger.critical(f'CANopen node {node.id.name} has sent no heartbeats in 60s after '
                                f'{self._MAX_CO_RESETS} resets, nod is now flagged as DEAD')
                node.set_as_dead()
            elif node.status == OpdNodeState.ON and co_status[1] + self._RESET_TIMEOUT_S < time():
                # card is on, but no CANopen heartbeat have been received in a minute, reset it
                logger.error(f'CANopen node {node.id.name} has sent no heartbeats in 60s, '
                             'resetting it')
                node.reset()
                self._co_resets[node.id] += 1
            else:
                self._co_resets[node.id] = 0

        return True
