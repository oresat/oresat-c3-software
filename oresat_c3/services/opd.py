''''
OPD (OreSat Power Domain) Service

Handle powering OreSat cards on and off.
'''

import json
from time import time

from olaf import Service, logger

from ..subsystems.opd import Opd, OpdNodeId, OpdNodeState
from .. import NodeId


OPD_NODE_TO_CO_NODE = {
    OpdNodeId.BATTERY_1: NodeId.BATTERY_1,
    OpdNodeId.GPS: NodeId.GPS,
    OpdNodeId.ACS: NodeId.ACS,
    OpdNodeId.DXWIFI: NodeId.DXWIFI,
    OpdNodeId.STAR_TRACKER_1: NodeId.STAR_TRACKER_1,
    OpdNodeId.BATTERY_2: NodeId.BATTERY_2,
    OpdNodeId.CFC_PROCESSOR: NodeId.CFC_PROCESSOR,
    # CFC_SENSOR is not a CANopen node
    OpdNodeId.RW_1: NodeId.RW_1,
    OpdNodeId.RW_2: NodeId.RW_2,
    OpdNodeId.RW_3: NodeId.RW_3,
    OpdNodeId.RW_4: NodeId.RW_4,
}


class OpdService(Service):

    _MAX_CO_RESETS = 3
    _RESET_TIMEOUT_S = 60
    _MONITOR_DELAY_S = 60

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd
        self.cur_node = list(OpdNodeId)[0]
        self._co_resets = {node.id: 0 for node in self.opd}

    def on_start(self):

        self._flight_mode_obj = self.node.od[0x3007][0x2]

        self.node.od[0x8001][0x2].value = '{}'
        self.node.add_sdo_read_callback(0x8001, self._on_read)
        self.node.add_sdo_write_callback(0x8001, self._on_write)

    def on_stop(self):

        self.opd.stop_loop = True

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

    def on_loop(self):
        '''Monitor all OPD nodes and check that nodes that are on are sending heartbeats.'''

        self.opd.monitor_nodes()

        if self.opd.is_subsystem_dead:
            self.sleep(self._MONITOR_DELAY_S)
            return

        if not self._flight_mode_obj.value:
            return True  # not in flight mode, do not monitor heartbeat

        for node in self.opd:
            if node.id == OpdNodeId.CFC_SENSOR or node.status == OpdNodeState.DEAD:
                self.sleep(self._MONITOR_DELAY_S)
                continue  # CFC_SENSOR not a CANopen node or node is dead

            co_node = OPD_NODE_TO_CO_NODE[node.id]
            co_status = self.node.node_status[co_node.value]
            if self._co_resets[node.id] >= self._MAX_CO_RESETS:
                logger.critical(f'CANopen node {node.id.name} has sent no heartbeats in 60s after '
                                f'{self._MAX_CO_RESETS} resets, now is now flagged as DEAD')
                node.set_as_dead()
            elif node.status == OpdNodeState.ON and co_status[1] + self._RESET_TIMEOUT_S < time():
                # card is on, but no CANopen heartbeat have been received in a minute, reset it
                logger.error(f'CANopen node {node.id.name} has sent no heartbeats in 60s, '
                             'resetting it')
                node.reset()
                self._co_resets[node.id] += 1
            else:
                self._co_resets[node.id] = 0

            self.sleep(self._MONITOR_DELAY_S)
