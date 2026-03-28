"""'
Node manager service.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, unique
from time import monotonic
from typing import Optional, Union

from olaf import Service, logger
from oresat_configs import Card

from ..subsystems.opd import Opd, OpdNode, OpdNodeState, OpdState, OpdStm32Node


@unique
class NodeState(Enum):
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


@dataclass
class Node:
    """Node data."""

    info: Card
    """Static info about this node's card."""
    opd_resets: int = field(init=False, default=0)
    """OPD reset count."""
    last_enable: float = field(init=False, default=0.0)
    """last enable timeout."""
    status: NodeState = field(init=False, default=NodeState.NOT_FOUND)
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

    def __init__(self, cards: dict[str, Card], *, mock_hw: bool = True) -> None:
        super().__init__()

        self.opd = Opd(
            self._NOT_ENABLE_PIN,
            self._NOT_FAULT_PIN,
            self._ADC_CURRENT_PIN,
            mock=mock_hw,
        )

        self._data = {}
        self.node_id_to_name = {}
        self.opd_addr_to_name = {0: "Invalid"}
        for name, info in cards.items():
            self._data[name] = Node(info)
            self.node_id_to_name[info.node_id] = name

            if info.opd_address == 0:
                continue  # not an opd node
            self.opd_addr_to_name[info.opd_address] = name
            self.opd.add_card(name, info, self._I2C_BUS_NUM)

        self._data["c3"].status = NodeState.ON

    def on_start(self) -> None:
        self._loops = -1

        # local objects
        self._flight_mode = self.node.od["flight_mode"]
        self._node_mgr = self.node.od["node_manager"]
        self._node_mgr["total_nodes"].value = len(self._data)

        self.opd.enable()

        self.node.add_sdo_callbacks("node_manager", "status_json", self._get_status_json, None)
        self.node.add_sdo_callbacks("opd", "status", self._get_opd_status, self._set_opd_status)
        self.node.add_sdo_callbacks(
            "opd",
            "uart_node_select",
            self._get_uart_node_select,
            self._set_uart_node_select,
        )
        for name, node in self._data.items():
            if node.info.node_id == 0:
                continue  # not a CANopen node
            self.node.add_sdo_callbacks(
                "node_status",
                name,
                lambda n=name: self.node_status(n),
                lambda v, n=name: self._set_node_status(n, v),
            )

    def _check_co_nodes_state(self, co: Node, last_hb: float) -> NodeState:
        """Get a CANopen node's state."""

        is_booting = monotonic() > last_hb + self._RESET_TIMEOUT_S

        if co.status == NodeState.DEAD:
            if is_booting:
                # if the node start sending heartbeats again (really only for flatsat)
                return NodeState.ON
            return NodeState.DEAD

        if co.info.processor == "stm32":
            timeout = self._STM32_BOOT_TIMEOUT
        else:
            timeout = self._OCTAVO_BOOT_TIMEOUT

        if co.last_enable + timeout > monotonic():
            if is_booting:
                return NodeState.BOOT
            return NodeState.ON
        if co.status == NodeState.ERROR:
            return NodeState.ERROR
        if self._flight_mode.value and self.node.bus_state == "NETWORK_UP" and is_booting:
            logger.error(
                f"Node {co.info.nice_name} has had no heartbeats in {self._RESET_TIMEOUT_S} seconds"
            )
            return NodeState.ERROR
        return NodeState.ON

    def _get_nodes_state(
        self, co: Node, opd: Optional[OpdNode], last_hb: Optional[float]
    ) -> NodeState:
        """Determine a node's state."""

        # update status of data not on the OPD
        if opd is None:
            if last_hb is None:
                raise ValueError("CO Node has no heartbeat")
            if monotonic() > last_hb + self._HB_TIMEOUT:
                return NodeState.OFF
            return NodeState.ON

        # opd subsystem is off
        if self.opd.status == OpdState.DISABLED:
            return NodeState.NOT_FOUND

        # update status of data on the OPD
        if self.opd.status == OpdState.DEAD:
            return NodeState.DEAD

        if co.opd_resets >= self._MAX_CO_RESETS:
            return NodeState.DEAD
        if opd.status == OpdNodeState.FAULT:
            return NodeState.ERROR
        if opd.status == OpdNodeState.NOT_FOUND:
            return NodeState.NOT_FOUND
        if opd.status == OpdNodeState.DISABLED:
            return NodeState.OFF
        if opd.status == OpdNodeState.ENABLED:
            if isinstance(opd, OpdStm32Node) and opd.in_bootloader_mode:
                return NodeState.BOOTLOADER
            if co.info.node_id != 0:  # aka CANopen nodes
                if last_hb is None:
                    raise ValueError("CO Node has no heartbeat")
                return self._check_co_nodes_state(co, last_hb)
            return NodeState.ON
        # default is last state -- opd dead
        return co.status

    def on_loop(self) -> None:
        """Monitor all OPD data and check that data that are on are sending heartbeats."""

        self._loops += 1
        self.sleep(1)

        count: Counter[NodeState] = Counter()
        for name, node in self._data.items():
            if name == "c3":
                continue

            last_state = node.status
            last_hb = self.node.node_status[name].time_since_boot if node.info.node_id else None
            state = self._get_nodes_state(
                node, self.opd[name] if node.info.opd_address else None, last_hb
            )
            count[state] += 1
            if self._loops != 0 and state != last_state:
                logger.info(f"node {name} state change {last_state.name} -> {state.name}")
            node.status = state

        self._node_mgr["nodes_off"].value = count[NodeState.OFF]
        self._node_mgr["nodes_booting"].value = count[NodeState.BOOT]
        self._node_mgr["nodes_on"].value = count[NodeState.ON]
        self._node_mgr["nodes_with_errors"].value = count[NodeState.ERROR]
        self._node_mgr["nodes_not_found"].value = count[NodeState.NOT_FOUND]
        self._node_mgr["nodes_dead"].value = count[NodeState.DEAD]

        if self.opd.status in [OpdState.DEAD, OpdState.DISABLED]:
            self._loops = -1
            return  # nothing to monitor

        if count[NodeState.NOT_FOUND] == len(self._data):
            self._loops = 0

        # reset nodes with errors and probe for nodes not found
        for name, node in self._data.items():
            try:
                opd = self.opd[name]
            except KeyError:
                continue

            if self._loops % 10 == 0 and node.status == NodeState.NOT_FOUND:
                opd.probe(reset=True)

            if node.info.opd_always_on and node.status == NodeState.OFF:
                self.enable(name)

            if node.status == NodeState.DEAD and opd.is_enabled:
                opd.disable()  # make sure this is disabled
            elif node.status == NodeState.ERROR:
                logger.error(f"resetting node {name}, try {node.opd_resets + 1}")
                opd.reset(1)
                node.last_enable = monotonic()
                node.opd_resets += 1
            elif node.status in (NodeState.ON, NodeState.OFF):
                node.opd_resets = 0

    def enable(self, name: Union[str, int], *, bootloader_mode: bool = False) -> None:
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
        if node.info.opd_address == 0:
            logger.warning(f"cannot enable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if node.status == NodeState.DEAD:
            logger.error(f"cannot enable node {name} as it is DEAD")
            return

        if node.status != NodeState.OFF:
            logger.debug(f"cannot enable node {name} unless it is disabled")
            return

        opd = self.opd[name]
        opd_child = self.opd[node.info.child] if node.info.child else None
        if isinstance(opd, OpdStm32Node):
            opd.enable(bootloader_mode=bootloader_mode)
            if isinstance(opd_child, OpdStm32Node):
                opd_child.enable(bootloader_mode=bootloader_mode)
            elif opd_child:
                opd_child.enable()
        else:
            opd.enable()
            if opd_child:
                opd_child.enable()
        node.last_enable = monotonic()

    def disable(self, name: Union[str, int]) -> None:
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
        child_node = self._data[node.info.child] if node.info.child else None
        if node.info.opd_address == 0:
            logger.warning(f"cannot disable node {name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if node.status in [NodeState.OFF, NodeState.DEAD]:
            logger.debug(f"cannot disable node {name} as it is already disabled or dead")
            return

        if child_node:
            self.opd[node.info.child].disable()
        self.opd[name].disable()

    def node_status(self, name: Union[str, int]) -> int:
        """Get the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        return self._data[name].status.value

    def _set_node_status(self, name: Union[str, int], value: int) -> None:
        """Set the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]
        try:
            state = NodeState(value)
        except ValueError:
            return

        if state == NodeState.ON:
            self.enable(name)
        elif state == NodeState.OFF:
            self.disable(name)
        elif state == NodeState.BOOTLOADER:
            self.enable(name, bootloader_mode=True)

    def _get_status_json(self) -> str:
        """SDO read callback to get the status of all data as a JSON."""

        data = []
        for name, node in self._data.items():
            data.append(
                {
                    "name": name,
                    "nice_name": node.info.nice_name,
                    "node_id": node.info.node_id,
                    "processor": node.info.processor,
                    "opd_addr": node.info.opd_address,
                    "status": node.status.name,
                }
            )
        return json.dumps(data)

    def _get_opd_status(self) -> int:
        return self.opd.status.value

    def _set_opd_status(self, value: int) -> None:
        if value == 0:
            self.opd.disable()
            for name, node in self._data.items():
                if node.info.opd_address != 0 and node.status != NodeState.NOT_FOUND:
                    logger.info(f"node {name} state change {node.status.name} -> NOT_FOUND")
                    node.status = NodeState.NOT_FOUND
        elif value == 1:
            if self.opd.status == OpdState.DISABLED:
                for node in self._data.values():
                    node.last_enable = monotonic()
            self.opd.enable()

    def _get_uart_node_select(self) -> int:
        """SDO write callback to select a node to connect to via UART."""

        return 0 if self.opd.uart_node is None else self._data[self.opd.uart_node].info.opd_address

    def _set_uart_node_select(self, value: int) -> None:
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
