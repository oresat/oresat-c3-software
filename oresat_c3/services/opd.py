"""'
OPD (OreSat Power Domain) Service

Handle powering OreSat cards on and off.
"""

import json
from time import time

import canopen
from olaf import Service, logger
from oresat_configs import NodeId

from ..subsystems.opd import Opd, OpdNodeId, OpdNodeState, OpdState

OPD_NODE_TO_CO_NODE = {
    OpdNodeId.BATTERY_1: NodeId.BATTERY_1,
    OpdNodeId.GPS: NodeId.GPS,
    OpdNodeId.IMU: NodeId.IMU,
    OpdNodeId.DXWIFI: NodeId.DXWIFI,
    OpdNodeId.STAR_TRACKER_1: NodeId.STAR_TRACKER_1,
    OpdNodeId.BATTERY_2: NodeId.BATTERY_2,
    OpdNodeId.CFC_PROCESSOR: NodeId.CFC,
    # CFC_SENSOR is not a CANopen node
    OpdNodeId.RW_1: NodeId.REACTION_WHEEL_1,
    OpdNodeId.RW_2: NodeId.REACTION_WHEEL_2,
    OpdNodeId.RW_3: NodeId.REACTION_WHEEL_3,
    OpdNodeId.RW_4: NodeId.REACTION_WHEEL_4,
}


class OpdService(Service):
    """OPD service."""

    _MAX_CO_RESETS = 3
    _RESET_TIMEOUT_S = 60
    _MONITOR_DELAY_S = 60

    def __init__(self, opd: Opd):
        super().__init__()

        self.opd = opd
        self.cur_node = list(OpdNodeId)[0]
        self._co_resets = {node.id: 0 for node in self.opd}

        self._flight_mode_obj: canopen.objectdictionary.Variable = None

    def on_start(self):
        self._flight_mode_obj = self.node.od["flight_mode"]
        self.node.od["opd"]["nodes_status_json"].value = "{}"

        self.node.add_sdo_callbacks("opd", "current", self._on_read_current, None)
        self.node.add_sdo_callbacks("opd", "status", self._on_read_status, self._on_write_status)
        self.node.add_sdo_callbacks("opd", "scan", None, self._on_write_scan)
        self.node.add_sdo_callbacks("opd", "nodes_status_json", self._on_read_status_json, None)
        self.node.add_sdo_callbacks(
            "opd", "node_select", self._on_read_node_select, self._on_write_node_select
        )
        self.node.add_sdo_callbacks(
            "opd", "node_status", self._on_read_node_status, self._on_write_node_status
        )
        self.node.add_sdo_callbacks("opd", "has_fault", self._on_read_has_fault, None)

    def on_loop(self):
        """Monitor all OPD nodes and check that nodes that are on are sending heartbeats."""

        self.sleep(self._MONITOR_DELAY_S)

        if self.opd.status == OpdState.DEAD:
            return

        self.opd.monitor_system()

        if not self._flight_mode_obj.value:
            return

        for node in self.opd:
            if node.id == OpdNodeId.CFC_SENSOR or node.status == OpdNodeState.DEAD:
                continue  # CFC_SENSOR not a CANopen node or node is dead

            co_node = OPD_NODE_TO_CO_NODE[node.id]
            try:
                co_status = self.node.node_status[co_node]
            except KeyError:
                continue  # not a valid node for this mission

            if self._co_resets[node.id] >= self._MAX_CO_RESETS:
                logger.critical(
                    f"CANopen node {node.id.name} has sent no heartbeats in "
                    f"{self._MONITOR_DELAY_S}s after {self._MAX_CO_RESETS} resets, "
                    "now is now flagged as DEAD"
                )
                node.set_as_dead()
            elif (
                node.status == OpdNodeState.ENABLED
                and co_status[1] + self._RESET_TIMEOUT_S < time()
            ):
                # card is on, but no CANopen heartbeat have been received in a minute, reset it
                logger.error(
                    f"CANopen node {node.id.name} has sent no heartbeats in 60s, resetting it"
                )
                node.reset()
                self._co_resets[node.id] += 1
            else:
                self._co_resets[node.id] = 0

    def on_stop(self):
        self.opd.stop_loop = True

    def _on_read_current(self) -> int:
        return self.opd.current

    def _on_read_status(self) -> int:
        return self.opd.status.value

    def _on_read_status_json(self) -> str:
        raw = {node.id.value: node.status.value for node in self.opd}
        return json.dumps(raw)

    def _on_read_node_select(self) -> int:
        return self.cur_node.value

    def _on_read_node_status(self) -> int:
        return self.opd[self.cur_node].status.value

    def _on_read_has_fault(self) -> bool:
        return self.opd.has_fault

    def _on_write_status(self, value: int):
        if value == OpdState.ENABLED:
            self.opd.enable()
        elif value == OpdState.DISABLED:
            self.opd.disable()

    def _on_write_node_select(self, value: int):
        self.cur_node = OpdNodeId(value)

    def _on_write_node_status(self, value: int):
        if value == OpdState.ENABLED:
            self.opd[self.cur_node].enable()
        elif value == OpdState.DISABLED:
            self.opd[self.cur_node].disable()

    def _on_write_scan(self, value: bool):
        if value:
            self.opd.scan(False)
