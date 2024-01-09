"""'
Node manager service.
"""

import json
from dataclasses import dataclass
from enum import IntEnum
from time import time
from typing import Union

import canopen
from dataclasses_json import dataclass_json
from olaf import Service, logger
from oresat_configs import Card

from ..subsystems.opd import Opd, OpdNode, OpdNodeState, OpdOctavoNode, OpdState, OpdStm32Node


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
            ON --> ERROR : Timeout with no heartbeats or OPD fault
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


@dataclass_json
@dataclass
class Node(Card):
    """Node data."""

    opd_resets: int = 0
    """OPD reset count."""
    last_enable: float = 0.0
    """last enable timeout."""
    status: NodeState = NodeState.OFF
    """Node status."""


class NodeManagerService(Service):
    """Node manager service."""

    _MAX_CO_RESETS = 3
    _RESET_TIMEOUT_S = 5
    _STM32_BOOT_TIMEOUT = 10
    _OCTAVO_BOOT_TIMEOUT = 90
    _HB_TIMEOUT = 5

    # opd hardware constants
    _NOT_ENABLE_PIN = "OPD_nENABLE"
    _NOT_FAULT_PIN = "OPD_nFAULT"
    _ADC_CURRENT_PIN = 2
    _I2C_BUS_NUM = 2

    def __init__(self, cards: dict, mock_hw: bool = True):
        super().__init__()

        self.opd = Opd(
            self._NOT_ENABLE_PIN,
            self._NOT_FAULT_PIN,
            self._ADC_CURRENT_PIN,
            mock=mock_hw,
        )

        for name, info in cards.items():
            if info.opd_address == 0:
                continue  # not an opd node

            if info.processor == "none":
                node = OpdNode(self._I2C_BUS_NUM, info.nice_name, info.opd_address, mock_hw)
            elif info.processor == "stm32":
                node = OpdStm32Node(self._I2C_BUS_NUM, info.nice_name, info.opd_address, mock_hw)
            elif info.processor == "octavo":
                node = OpdOctavoNode(self._I2C_BUS_NUM, info.nice_name, info.opd_address, mock_hw)
            else:
                continue

            self.opd[name] = node

        self.opd_addr_to_name = {info.opd_address: name for name, info in cards.items()}
        self.node_id_to_name = {info.node_id: name for name, info in cards.items()}

        self._data = {name: Node(**info.to_dict()) for name, info in cards.items()}
        self._data["c3"].status = NodeState.ON
        self._loops = -1

        self._flight_mode_obj: canopen.objectdictionary.Variable = None
        self._nodes_off_obj: canopen.objectdictionary.Variable = None
        self._nodes_booting_obj: canopen.objectdictionary.Variable = None
        self._nodes_on_obj: canopen.objectdictionary.Variable = None
        self._nodes_with_errors_obj: canopen.objectdictionary.Variable = None
        self._nodes_not_found_obj: canopen.objectdictionary.Variable = None
        self._nodes_dead_obj: canopen.objectdictionary.Variable = None

        self.opd.enable()

    def on_start(self):
        # local objects
        self._flight_mode_obj = self.node.od["flight_mode"]
        nodes_mgr_rec = self.node.od["node_manager"]
        self._nodes_off_obj = nodes_mgr_rec["nodes_off"]
        self._nodes_booting_obj = nodes_mgr_rec["nodes_booting"]
        self._nodes_on_obj = nodes_mgr_rec["nodes_on"]
        self._nodes_not_found_obj = nodes_mgr_rec["nodes_not_found"]
        self._nodes_with_errors_obj = nodes_mgr_rec["nodes_with_errors"]
        self._nodes_dead_obj = nodes_mgr_rec["nodes_dead"]
        nodes_mgr_rec["total_nodes"].value = len(list(self._data))

        self.node.add_sdo_callbacks("node_manager", "status_json", self._get_status_json, None)
        self.node.add_sdo_callbacks("opd", "status", self._get_opd_status, self._set_opd_status)
        for name in self._data:
            if self._data[name].node_id == 0:
                continue  # not a CANopen node
            self.node.add_sdo_callbacks(
                "node_status",
                str(name),
                lambda n=name: self.node_status(n),
                lambda v, n=name: self.enable(n) if v == NodeState.ON else self.disable(n),
            )

    def _check_co_nodes_state(self, name: str) -> NodeState:
        """Get a CANopen node's state."""

        next_state = self._data[name].status
        if next_state == NodeState.DEAD:
            return next_state

        if self._data[name].processor == "stm32":
            timeout = self._STM32_BOOT_TIMEOUT
        else:
            timeout = self._OCTAVO_BOOT_TIMEOUT

        last_hb = self.node.node_status[name][1]
        if self._data[name].last_enable + timeout > time():
            if time() > last_hb + self._RESET_TIMEOUT_S:
                next_state = NodeState.BOOT
            else:
                next_state = NodeState.ON
        elif self._flight_mode_obj.value and time() > last_hb + self._RESET_TIMEOUT_S:
            logger.error(
                f"CANopen node {name} has had no heartbeats in " f"{self._RESET_TIMEOUT_S} seconds"
            )
            next_state = NodeState.ERROR
        else:
            next_state = NodeState.ON

        return next_state

    def _get_nodes_state(self, name: str) -> NodeState:
        """Determine a node's state."""

        # update status of data not on the OPD
        if self._data[name].opd_address == 0:
            if time() > self.node.node_status[name][1] + self._HB_TIMEOUT:
                next_state = NodeState.OFF
            else:
                next_state = NodeState.ON
            return next_state

        # opd subsystem is off
        if self.opd.status == OpdState.DISABLED:
            return NodeState.NOT_FOUND

        prev_state = self._data[name].status

        # default is last state
        next_state = prev_state

        # update status of data on the OPD
        if self.opd.status == OpdState.DEAD:
            next_state = NodeState.DEAD
        else:
            status = self.opd[name].status
            if status == OpdNodeState.FAULT:
                next_state = NodeState.ERROR
            elif status == OpdNodeState.NOT_FOUND:
                next_state = NodeState.NOT_FOUND
            elif (
                prev_state == NodeState.ERROR and self._data[name].opd_resets >= self._MAX_CO_RESETS
            ):
                next_state = NodeState.DEAD
            elif status == OpdNodeState.ENABLED:
                if self._data[name].node_id != 0:  # aka CANopen nodes
                    next_state = self._check_co_nodes_state(name)
                else:
                    next_state = NodeState.ON
            elif status == OpdNodeState.DISABLED:
                next_state = NodeState.OFF

        return next_state

    def on_loop(self):
        """Monitor all OPD data and check that data that are on are sending heartbeats."""

        self._loops += 1
        self.sleep(1)

        nodes_off = 0
        nodes_booting = 0
        nodes_on = 0
        nodes_with_errors = 0
        nodes_not_found = 0
        nodes_dead = 0
        for name in self._data:
            if name == "c3":
                continue

            last_state = self._data[name].status
            state = self._get_nodes_state(name)
            if state != last_state:
                logger.info(f"node {name} state change {last_state.name} -> {state.name}")
            nodes_off += int(state == NodeState.OFF)
            nodes_booting += int(state == NodeState.BOOT)
            nodes_on += int(state == NodeState.ON)
            nodes_with_errors += int(state == NodeState.ERROR)
            nodes_not_found += int(state == NodeState.NOT_FOUND)
            nodes_dead += int(state == NodeState.DEAD)
            self._data[name].status = state
        self._nodes_off_obj.value = nodes_off
        self._nodes_booting_obj.value = nodes_booting
        self._nodes_on_obj.value = nodes_on
        self._nodes_with_errors_obj.value = nodes_with_errors
        self._nodes_not_found_obj.value = nodes_not_found
        self._nodes_dead_obj.value = nodes_dead

        if self.opd.status in [OpdState.DEAD, OpdState.DISABLED]:
            self._loops = -1
            return  # nothing to monitor

        # reset data with errors and probe for data not found
        for name, info in self._data.items():
            if info.opd_address == 0:
                continue

            if self._loops % 60 == 0 and self._data[name].status == NodeState.NOT_FOUND:
                self.opd[name].probe(True)

            if info.opd_always_on and info.status == NodeState.OFF:
                self.enable(name)

            if info.status == NodeState.ERROR:
                logger.error(f"resetting node {name}, try {info.opd_resets + 1}")
                self.opd[name].reset(1)
                info.opd_resets += 1
            else:
                info.opd_resets = 0

    def enable(self, name: Union[str, int]):
        """Enable a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        node = self._data[name]
        child_node = self._data[node.child] if node.child else None
        if node.opd_address == 0:
            logger.warning(f"cannot enable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if node.status == NodeState.DEAD:
            logger.error(f"cannot enable node {name} as it is DEAD")
            return

        self.opd[name].enable()
        if child_node:
            self.opd[node.child].enable()
        node.last_enable = time()

    def disable(self, name: Union[str, int]):
        """Disable a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        node = self._data[name]
        child_node = self._data[node.child] if node.child else None
        if node.opd_address == 0:
            logger.warning(f"cannot disable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if child_node:
            self.opd[node.child].disable()

        self.opd[name].disable()

    def node_status(self, name: Union[str, int]) -> NodeState:
        """Get the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        return self._data[name].status

    def _get_status_json(self) -> str:
        """SDO read callback to get the status of all data as a JSON."""

        data = []
        for name, info in self._data.items():
            data.append(
                {
                    "name": name,
                    "nice_name": info.nice_name,
                    "node_id": info.node_id,
                    "opd_addr": info.opd_address,
                    "status": info.status.name,
                }
            )
        return json.dumps(data)

    def _get_opd_status(self) -> int:
        return self.opd.status.value

    def _set_opd_status(self, value: int):
        if value == 0:
            self.opd.disable()
        elif value == 1:
            if self.opd.status == OpdState.DISABLED:
                for node in self._data.values():
                    node.last_enable = time()
            self.opd.enable()
