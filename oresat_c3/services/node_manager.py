"""'
Node manager service.
"""

import json
from dataclasses import asdict, dataclass
from enum import IntEnum
from time import monotonic
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
            OFF --> BOOT : Enable
            OFF --> BOOTLOADER : Bootloader (STM32 only)
            BOOTLOADER --> OFF : Disable
            BOOT --> OFF : Disable
            BOOT --> ON : Heartbeats and no OPD fault
            BOOT --> ERROR : Timeout with no heartbeats or OPD fault
            ERROR --> DEAD : Multiple resets failed in a row
            ERROR --> ON : Reset
            ERROR --> OFF : Disable
            ON --> OFF : Disable
            ON --> ERROR : Timeout with no heartbeats or OPD fault
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
    BOOTLOADER = 5
    """For STM32s on the OPD only: Bootloader mode (used to reflash the app)."""
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
    status: NodeState = NodeState.NOT_FOUND
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

        self._data = {name: Node(**asdict(info)) for name, info in cards.items()}
        self._data["c3"].status = NodeState.ON
        self._loops = -1

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
        nodes_mgr_rec = self.node.od["node_manager"]
        self._nodes_off_obj = nodes_mgr_rec["nodes_off"]
        self._nodes_booting_obj = nodes_mgr_rec["nodes_booting"]
        self._nodes_on_obj = nodes_mgr_rec["nodes_on"]
        self._nodes_not_found_obj = nodes_mgr_rec["nodes_not_found"]
        self._nodes_with_errors_obj = nodes_mgr_rec["nodes_with_errors"]
        self._nodes_dead_obj = nodes_mgr_rec["nodes_dead"]
        nodes_mgr_rec["total_nodes"].value = len(list(self._data))

        self.opd.enable()

        self.node.add_sdo_callbacks("node_manager", "status_json", self._get_status_json, None)
        self.node.add_sdo_callbacks("opd", "status", self._get_opd_status, self._set_opd_status)
        self.node.add_sdo_callbacks(
            "opd",
            "uart_node_select",
            self._get_uart_node_select,
            self._set_uart_node_select,
        )
        for name in self._data:
            if self._data[name].node_id == 0:
                continue  # not a CANopen node
            self.node.add_sdo_callbacks(
                "node_status",
                str(name),
                lambda n=name: self.node_status(n),
                lambda v, n=name: self._set_node_status(n, v),
            )

    def _check_co_nodes_state(self, name: str) -> NodeState:
        """Get a CANopen node's state."""

        node = self._data[name]
        next_state = node.status
        last_hb = self.node.node_status[name][2]

        if next_state == NodeState.DEAD:
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                # if the node start sending heartbeats again (really only for flatsat)
                next_state = NodeState.ON
            return next_state

        if node.processor == "stm32":
            timeout = self._STM32_BOOT_TIMEOUT
        else:
            timeout = self._OCTAVO_BOOT_TIMEOUT

        if node.last_enable + timeout > monotonic():
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                next_state = NodeState.BOOT
            else:
                next_state = NodeState.ON
        elif node.status == NodeState.ERROR:
            next_state = NodeState.ERROR
        elif (
            self._flight_mode_obj.value
            and self.node.bus_state == "NETWORK_UP"
            and monotonic() > (last_hb + self._RESET_TIMEOUT_S)
        ):
            logger.error(
                f"CANopen node {name} has had no heartbeats in {self._RESET_TIMEOUT_S} seconds"
            )
            next_state = NodeState.ERROR
        else:
            next_state = NodeState.ON

        return next_state

    def _get_nodes_state(self, name: str) -> NodeState:
        """Determine a node's state."""

        # update status of data not on the OPD
        if self._data[name].opd_address == 0:
            if monotonic() > (self.node.node_status[name][2] + self._HB_TIMEOUT):
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
            if self._data[name].opd_resets >= self._MAX_CO_RESETS:
                next_state = NodeState.DEAD
            elif status == OpdNodeState.FAULT:
                next_state = NodeState.ERROR
            elif status == OpdNodeState.NOT_FOUND:
                next_state = NodeState.NOT_FOUND
            elif status == OpdNodeState.ENABLED:
                if self._data[name].processor == "stm32" and self.opd[name].in_bootloader_mode:
                    next_state = NodeState.BOOTLOADER
                elif self._data[name].node_id != 0:  # aka CANopen nodes
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
        for name, node in self._data.items():
            if name == "c3":
                continue

            last_state = node.status
            state = self._get_nodes_state(name)
            if self._loops != 0 and state != last_state:
                logger.info(f"node {name} state change {last_state.name} -> {state.name}")
            nodes_off += int(state == NodeState.OFF)
            nodes_booting += int(state == NodeState.BOOT)
            nodes_on += int(state == NodeState.ON)
            nodes_with_errors += int(state == NodeState.ERROR)
            nodes_not_found += int(state == NodeState.NOT_FOUND)
            nodes_dead += int(state == NodeState.DEAD)
            node.status = state
        self._nodes_off_obj.value = nodes_off
        self._nodes_booting_obj.value = nodes_booting
        self._nodes_on_obj.value = nodes_on
        self._nodes_with_errors_obj.value = nodes_with_errors
        self._nodes_not_found_obj.value = nodes_not_found
        self._nodes_dead_obj.value = nodes_dead

        if self.opd.status in [OpdState.DEAD, OpdState.DISABLED]:
            self._loops = -1
            return  # nothing to monitor

        if nodes_not_found == len(self._data):
            self._loops = 0

        # reset nodes with errors and probe for nodes not found
        for name, info in self._data.items():
            if info.opd_address == 0:
                continue

            if self._loops % 10 == 0 and self._data[name].status == NodeState.NOT_FOUND:
                self.opd[name].probe(True)

            if info.opd_always_on and info.status == NodeState.OFF:
                self.enable(name)

            if info.status == NodeState.DEAD and self.opd[name].is_enabled:
                self.opd[name].disable()  # make sure this is disabled
            elif info.status == NodeState.ERROR:
                logger.error(f"resetting node {name}, try {info.opd_resets + 1}")
                self.opd[name].reset(1)
                self._data[name].last_enable = monotonic()
                info.opd_resets += 1
            elif info.status in [NodeState.ON, NodeState.OFF]:
                info.opd_resets = 0

    def enable(self, name: Union[str, int], bootloader_mode: bool = False):
        """
        Enable a OreSat node.

        Parameters
        ----------
        name: str | int
            Name or node id of the card to enable
        bootloader_mode: bool
            Go into bootloader mode instead. Only for STM32 nodes on the OPD, flag will be ignored
            otherwise.
        """

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        node = self._data[name]
        child_node = self._data[node.child] if node.child else None
        if node.opd_address == 0:
            logger.warning(f"cannot enable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if node.status != NodeState.OFF:
            logger.debug(f"cannot enable node {name} unless it is disabled")
            return

        if node.status == NodeState.DEAD:
            logger.error(f"cannot enable node {name} as it is DEAD")
            return

        if node.processor == "stm32":
            self.opd[name].enable(bootloader_mode)
            if child_node:
                self.opd[node.child].enable(bootloader_mode)
        else:
            self.opd[name].enable()
            if child_node:
                self.opd[node.child].enable()
        node.last_enable = monotonic()

    def disable(self, name: Union[str, int]):
        """
        Disable a OreSat node.

        Parameters
        ----------
        name: str | int
            Name or node id of the card to enable
        """

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        node = self._data[name]
        child_node = self._data[node.child] if node.child else None
        if node.opd_address == 0:
            logger.warning(f"cannot disable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if node.status in [NodeState.OFF, NodeState.DEAD]:
            logger.debug(f"cannot disable node {name} as it is already disabled or dead")
            return

        if child_node:
            self.opd[node.child].disable()
        self.opd[name].disable()

    def node_status(self, name: Union[str, int]) -> NodeState:
        """Get the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        return self._data[name].status

    def _set_node_status(self, name: Union[str, int], state: int):
        """Set the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        if state == NodeState.ON:
            self.enable(name)
        elif state == NodeState.OFF:
            self.disable(name)
        elif state == NodeState.BOOTLOADER:
            self.enable(name, True)

    def _get_status_json(self) -> str:
        """SDO read callback to get the status of all data as a JSON."""

        data = []
        for name, info in self._data.items():
            data.append(
                {
                    "name": name,
                    "nice_name": info.nice_name,
                    "node_id": info.node_id,
                    "processor": info.processor,
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
            for name, node in self._data.items():
                if node.opd_address != 0 and node.status != NodeState.NOT_FOUND:
                    logger.info(f"node {name} state change {node.status.name} -> NOT_FOUND")
                    node.status = NodeState.NOT_FOUND
        elif value == 1:
            if self.opd.status == OpdState.DISABLED:
                for node in self._data.values():
                    node.last_enable = monotonic()
            self.opd.enable()

    def _get_uart_node_select(self) -> int:
        """SDO write callback to select a node to connect to via UART."""

        return 0 if self.opd.uart_node is None else self._data[self.opd.uart_node].opd_address

    def _set_uart_node_select(self, value: int):
        """
        SDO write callback to select a node to connect to via UART.

        Parameters
        ----------
        value: int
            The opd address of the node to connect to UART or 0 for no node.
        """

        if value == 0:
            self.opd.uart_node = None
        elif value in self.opd_addr_to_name:
            self.opd.uart_node = self.opd_addr_to_name[value]
