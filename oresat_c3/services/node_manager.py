"""'
Node manager service.
"""

import json
from time import time
from enum import IntEnum
from typing import Union

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

CO_TO_OPD = {
    NodeId.BATTERY_1: OpdNodeId.BATTERY_1,
    NodeId.BATTERY_2: OpdNodeId.BATTERY_2,
    NodeId.IMU: OpdNodeId.IMU,
    NodeId.REACTION_WHEEL_1: OpdNodeId.RW_1,
    NodeId.REACTION_WHEEL_2: OpdNodeId.RW_2,
    NodeId.REACTION_WHEEL_3: OpdNodeId.RW_3,
    NodeId.REACTION_WHEEL_4: OpdNodeId.RW_4,
    NodeId.GPS: OpdNodeId.GPS,
    NodeId.STAR_TRACKER_1: OpdNodeId.STAR_TRACKER_1,
    NodeId.DXWIFI: OpdNodeId.DXWIFI,
}

NODES_NOT_ON_OPD = [
    NodeId.SOLAR_MODULE_1,
    NodeId.SOLAR_MODULE_2,
    NodeId.SOLAR_MODULE_3,
    NodeId.SOLAR_MODULE_4,
    NodeId.SOLAR_MODULE_5,
    NodeId.SOLAR_MODULE_6,
    NodeId.SOLAR_MODULE_7,
    NodeId.SOLAR_MODULE_8,
]

ORESAT1_NODES = [
    NodeId.STAR_TRACKER_2,
    NodeId.BATTERY_2,
    NodeId.SOLAR_MODULE_7,
    NodeId.SOLAR_MODULE_8,
]


class NodeState(IntEnum):
    """
    OreSat Node States

    .. mermaid
        stateDiagram-v2
            [*] --> OFF
            OFF--> BOOT : Enable
            BOOT --> OFF : Disable
            BOOT --> ON : Heartbeats and no OPD fault
            BOOT --> ERROR : Timeout with no heartbeats or OPD fault
            ON --> OFF : Disable
            ON --> ERROR : No heartbeats or OPD fault
            ERROR --> OFF : Disable
            ERROR --> ON : Reset
            ERROR --> DEAD : Multiple resets failed in a row
    """

    OFF = 0
    """Node is powered off."""
    BOOT = 1
    """Node is booting."""
    ON = 2
    """Node is powered on."""
    ERROR = 3
    """Node is not sending heartbeats or has a OPD fault."""
    NOT_FOUND = 4
    """Node is not found on the OPD."""
    DEAD = 0xFF
    """Node has failed to clear errors after multiple resets."""


class NodeManagerService(Service):
    """Node manager service."""

    _MAX_CO_RESETS = 3
    _RESET_TIMEOUT_S = 5

    def __init__(self, opd: Opd):
        super().__init__()

        nodes = list(NodeId)
        self._opd = opd
        self._opd_resets = {node.id: 0 for node in self._opd}
        self._status = {node: NodeState.OFF for node in nodes}

        self._loops = 0

        self._flight_mode_obj: canopen.objectdictionary.Variable = None
        self._nodes_off_obj: canopen.objectdictionary.Variable = None
        self._nodes_booting_obj: canopen.objectdictionary.Variable = None
        self._nodes_on_obj: canopen.objectdictionary.Variable = None
        self._nodes_with_errors_obj: canopen.objectdictionary.Variable = None
        self._nodes_not_found_obj: canopen.objectdictionary.Variable = None
        self._nodes_dead_obj: canopen.objectdictionary.Variable = None

    def on_start(self):
        # local objects
        self._flight_mode_obj = self.node.od["flight_mode"]
        node_mgr_rec = self.node.od['node_manager']
        self._nodes_off_obj = node_mgr_rec['nodes_off']
        self._nodes_booting_obj = node_mgr_rec['nodes_booting']
        self._nodes_on_obj = node_mgr_rec['nodes_on']
        self._nodes_not_found_obj = node_mgr_rec['nodes_not_found']
        self._nodes_with_errors_obj = node_mgr_rec['nodes_with_errors']
        self._nodes_dead_obj = node_mgr_rec['nodes_dead']
        node_mgr_rec['total_nodes'].value = len(list(NodeId))

        self.node.add_sdo_callbacks("node_manager", "status_json", self._get_status_json, None)
        for node_id in list(NodeId):
            if node_id in [NodeId.C3] + ORESAT1_NODES:
                continue
            name = node_id.name.lower()
            self.node.add_sdo_callbacks(
                "node_status",
                name,
                lambda n=node_id: self.status(n),
                lambda v, n=node_id: self.enable(n) if v == NodeState.ON else self.disable(n),
            )

    def _check_co_node_state(self, node_id: NodeId) -> NodeState:
        """Get a CANopen node's state."""

        next_state = self._status[node_id]
        if next_state == NodeState.DEAD:
            return next_state

        last_hb = self.node.node_status[node_id][1]
        if self._flight_mode_obj.value and time() > last_hb + self._RESET_TIMEOUT_S:
            logger.error(
                f"CANopen node {node_id.name} has had no heartbeats in "
                f"{self._RESET_TIMEOUT_S} seconds"
            )
            next_state = NodeState.ERROR
        else:
            next_state = NodeState.ON

        return next_state

    def _get_node_state(self, node_id: NodeId) -> NodeState:
        """Determine a node's state."""

        if node_id == NodeId.C3:
            return NodeState.ON

        if node_id not in self.node.node_status:
            return NodeState.NOT_FOUND

        # update status of nodes not on the OPD
        if node_id in NODES_NOT_ON_OPD:
            if time() > self.node.node_status[node_id][1] + 1:
                next_state = NodeState.OFF
            else:
                next_state = NodeState.ON
            return next_state

        prev_state = self._status[node_id]

        # default is last state
        next_state = prev_state

        # update status of nodes on the OPD
        if self._opd.status == OpdState.DEAD:
            next_state = NodeState.DEAD
        elif node_id != NodeId.CFC:
            opd_node_id = CO_TO_OPD[node_id]
            status = self._opd[opd_node_id].status
            if status == OpdNodeState.FAULT:
                next_state = NodeState.ERROR
            elif status == OpdNodeState.NOT_FOUND:
                next_state = NodeState.NOT_FOUND
            elif prev_state == NodeState.ERROR \
                    and self._opd_resets[opd_node_id] >= self._MAX_CO_RESETS:
                next_state = NodeState.DEAD
            elif status == OpdNodeState.ENABLED:
                next_state = self._check_co_node_state(node_id)
            elif status == OpdNodeState.DISABLED:
                next_state = NodeState.OFF
        else:
            pro_status = self._opd[OpdNodeId.CFC_PROCESSOR].status
            sen_status = self._opd[OpdNodeId.CFC_SENSOR].status
            if OpdNodeState.NOT_FOUND in [pro_status, sen_status]:
                next_state = NodeState.NOT_FOUND
            elif prev_state == NodeState.ERROR \
                    and self._opd_resets[OpdNodeId.CFC_PROCESSOR] >= self._MAX_CO_RESETS:
                next_state = NodeState.DEAD
            elif OpdNodeState.ENABLED in [pro_status, sen_status]:
                next_state = self._check_co_node_state(node_id)
            elif pro_status == OpdNodeState.DISABLED and sen_status == OpdNodeState.DISABLED:
                next_state = NodeState.OFF
            else:  # one card is on and other is not
                next_state = NodeState.ERROR

        if prev_state != next_state:
            logger.info(
                f"node {node_id.name} state change {prev_state.name} -> {next_state.name}"
            )

        return next_state

    def on_loop(self):
        """Monitor all OPD nodes and check that nodes that are on are sending heartbeats."""

        self.sleep(1)

        nodes_off = 0
        nodes_booting = 0
        nodes_on = 0
        nodes_with_errors = 0
        nodes_not_found = 0
        nodes_dead = 0
        for node_id in list(NodeId):
            state = self._get_node_state(node_id)
            nodes_off += int(state == NodeState.OFF)
            nodes_booting += int(state == NodeState.BOOT)
            nodes_on += int(state == NodeState.ON)
            nodes_with_errors += int(state == NodeState.ERROR)
            nodes_not_found += int(state == NodeState.NOT_FOUND)
            nodes_dead += int(state == NodeState.DEAD)
            self._status[node_id] = state
        self._nodes_off_obj.value = nodes_off
        self._nodes_booting_obj.value = nodes_booting
        self._nodes_on_obj.value = nodes_on
        self._nodes_with_errors_obj.value = nodes_with_errors
        self._nodes_not_found_obj.value = nodes_not_found
        self._nodes_dead_obj.value = nodes_dead

        if self._opd.status == OpdState.DEAD:
            return

        if not self._flight_mode_obj.value:
            return  # don't reset card when not in flight mode as someone may be debugging it

        # reset nodes with errors and probe for nodes not found
        for node_id in list(NodeId):
            if node_id in NODES_NOT_ON_OPD + [NodeId.C3] + ORESAT1_NODES:
                continue

            opd_node_id = CO_TO_OPD.get(node_id, None)

            if self._loops % 60 == 0 and self._status[node_id] == NodeState.NOT_FOUND:
                if node_id != NodeId.CFC:
                    self._opd[opd_node_id].probe(True)
                else:
                    self._opd[OpdNodeId.CFC_PROCESSOR].probe(True)
                    self._opd[OpdNodeId.CFC_SENSOR].probe(True)

            if self._status[node_id] == NodeState.ERROR:
                if node_id != NodeId.CFC:
                    logger.error(
                        f"resetting node {node_id.name}, try {self._opd_resets[opd_node_id] + 1}"
                    )
                    self._opd[opd_node_id].reset(1)
                    self._opd_resets[opd_node_id] += 1
                else:
                    logger.error(
                        f"resetting node {node_id.name}, try "
                        f"{self._opd_resets[OpdNodeId.CFC_PROCESSOR] + 1}"
                    )
                    self._opd[OpdNodeId.CFC_PROCESSOR].reset(1)
                    self._opd_resets[OpdNodeId.CFC_PROCESSOR] += 1
                    self._opd[OpdNodeId.CFC_SENSOR].reset()
                    self._opd_resets[OpdNodeId.CFC_SENSOR] += 1
            else:
                self._opd_resets[opd_node_id] = 0

        self._loops += 1

    def enable(self, node_id: Union[NodeId, int]):
        """Enable a OreSat node."""

        if not isinstance(node_id, NodeId):
            node_id = NodeId(node_id)

        if node_id in NODES_NOT_ON_OPD:
            return  # do nothing

        if self._status[node_id] == NodeState.DEAD:
            logger.warning(f"cannot enable node {node_id.name} as it is DEAD")
            return

        if node_id == NodeId.CFC:
            self._opd[OpdNodeId.CFC_PROCESSOR].enable()
            self._opd[OpdNodeId.CFC_SENSOR].enable()
        elif node_id not in NODES_NOT_ON_OPD:
            self._opd[CO_TO_OPD[node_id]].enable()

    def disable(self, node_id: Union[NodeId, int]):
        """Disable a OreSat node."""

        if not isinstance(node_id, NodeId):
            node_id = NodeId(node_id)

        if node_id in NODES_NOT_ON_OPD:
            return  # do nothing

        if node_id == NodeId.CFC:
            self._opd[OpdNodeId.CFC_PROCESSOR].disable()
            self._opd[OpdNodeId.CFC_SENSOR].disable()
        elif node_id not in NODES_NOT_ON_OPD:
            self._opd[CO_TO_OPD[node_id]].disable()

    def status(self, node_id: Union[NodeId, int]) -> NodeState:
        """Get the status of a OreSat node."""

        if not isinstance(node_id, NodeId):
            node_id = NodeId(node_id)

        return self._status[node_id]

    def _get_status_json(self) -> str:
        """SDO read callback to get the status of all nodes as a JSON."""

        data = []
        for node, status in self._status.items():
            if node in [NodeId.C3] + ORESAT1_NODES:
                continue
            on_opd = "SOLAR" not in node.name
            data.append({
                "node_name": node.name,
                "node_id": node.value,
                "node_status_name": status.name,
                "node_status": status.value,
                "on_opd": on_opd,
            })
        return json.dumps(data)
