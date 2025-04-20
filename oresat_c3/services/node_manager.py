import json
from dataclasses import asdict, dataclass, field
from time import monotonic
from typing import Optional, Union

from loguru import logger
from oresat_canopend import NodeClient
from oresat_canopend import NodeState as CanopenNodeState

from ..gen.c3_od import C3Entry, C3NodeStatus, C3OpdNodeStatus
from ..gen.missions import Mission
from ..gen.nodes import NodeDef, NodeProcessor
from ..subsystems.opd import Opd, OpdNode, OpdOctavoNode, OpdState, OpdStm32Node
from . import Service


@dataclass
class Emcy:
    code: int
    info: int
    time: float


@dataclass
class NodeData(NodeDef):
    opd_resets: int = 0
    last_enable: float = 0.0
    status: C3NodeStatus = C3NodeStatus.NOT_FOUND
    last_hb: float = 0.0
    hb_state: Optional[CanopenNodeState] = None
    emcys: list[Emcy] = field(default_factory=list)


class NodeManagerService(Service):
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

    def __init__(self, node: NodeClient, mock_hw: bool = True):
        super().__init__(node)

        self.opd = Opd(
            self._NOT_ENABLE_PIN,
            self._NOT_FAULT_PIN,
            self._ADC_CURRENT_PIN,
            mock=mock_hw,
        )

        sat_id = self.node.od_read(C3Entry.SATELLITE_ID)
        self.mission = Mission.from_id(sat_id)

        for card in self.mission.nodes:
            if card.opd_address == 0:
                continue  # not an opd node

            if card.processor == NodeProcessor.NONE:
                node = OpdNode(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            elif card.processor == NodeProcessor.STM32:
                node = OpdStm32Node(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            elif card.processor == NodeProcessor.OCTAVO:
                node = OpdOctavoNode(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            else:
                continue

            self.opd[card.name] = node

        self.opd_addr_to_name = {card.opd_address: card.name for card in self.mission.nodes}
        self.node_id_to_name = {card.node_id: card.name for card in self.mission.nodes}

        self._data = {card.name: NodeData(**asdict(card)) for card in self.mission.nodes}
        self._loops = -1

        self.node.od_write(C3Entry.NODE_MANAGER_TOTAL_NODES, len(list(self._data)))

        self.opd.enable()

        self.node.add_write_callback(C3Entry.OPD_STATUS, self._set_opd_status)
        self.node.add_write_callback(C3Entry.OPD_UART_NODE_SELECT, self._set_uart_node_select)

        for name in self._data:
            card = self._data[name]
            if card.node_id == 0:
                continue  # not a CANopen node
            self.node.add_write_callback(
                C3Entry[f"NODE_STATUS_NODE_ID_{card.node_id}".upper()],
                lambda v, n=name: self._set_node_status(n, v),
            )

        self.node.add_heartbeat_callback(self._hb_cb)
        self.node.add_emcy_callback(self._emcy_cb)

    def _hb_cb(self, node_id: int, state: CanopenNodeState):
        name = self.node_id_to_name[node_id]
        self._data[name].hb_state = state
        self._data[name].last_hb = monotonic()

    def _emcy_cb(self, node_id: int, code: int, info: int):
        name = self.node_id_to_name[node_id]
        emcy = Emcy(code, info, monotonic())
        self._data[name].emcys.append(emcy)

    def _check_co_nodes_state(self, name: str) -> C3NodeStatus:
        """Get a CANopen node's state."""

        node = self._data[name]
        next_state = node.status
        last_hb = self._data[name].last_hb

        if next_state == C3NodeStatus.DEAD:
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                # if the node start sending heartbeats again (really only for flatsat)
                next_state = C3NodeStatus.ON
            return next_state

        if node.processor == "stm32":
            timeout = self._STM32_BOOT_TIMEOUT
        else:
            timeout = self._OCTAVO_BOOT_TIMEOUT

        if node.last_enable + timeout > monotonic():
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                next_state = C3NodeStatus.BOOT
            else:
                next_state = C3NodeStatus.ON
        elif node.status == C3NodeStatus.ERROR:
            next_state = C3NodeStatus.ERROR
        elif (
            self.node.od_read(C3Entry.FLIGHT_MODE)
            and self.node.bus_state == "NETWORK_UP"
            and monotonic() > (last_hb + self._RESET_TIMEOUT_S)
        ):
            logger.error(
                f"CANopen node {name} has had no heartbeats in {self._RESET_TIMEOUT_S} seconds"
            )
            next_state = C3NodeStatus.ERROR
        else:
            next_state = C3NodeStatus.ON

        return next_state

    def _get_nodes_state(self, name: str) -> C3NodeStatus:
        """Determine a node's state."""

        # update status of data not on the OPD
        if self._data[name].opd_address == 0:
            if monotonic() > (self._data[name].last_hb + self._HB_TIMEOUT):
                next_state = C3NodeStatus.OFF
            else:
                next_state = C3NodeStatus.ON
            return next_state

        # opd subsystem is off
        if self.opd.status == OpdState.DISABLED:
            return C3NodeStatus.NOT_FOUND

        prev_state = self._data[name].status

        # default is last state
        next_state = prev_state

        # update status of data on the OPD
        if self.opd.status == OpdState.DEAD:
            next_state = C3NodeStatus.DEAD
        else:
            status = self.opd[name].status
            if self._data[name].opd_resets >= self._MAX_CO_RESETS:
                next_state = C3NodeStatus.DEAD
            elif status == C3OpdNodeStatus.FAULT:
                next_state = C3NodeStatus.ERROR
            elif status == C3OpdNodeStatus.NOT_FOUND:
                next_state = C3NodeStatus.NOT_FOUND
            elif status == C3OpdNodeStatus.ENABLED:
                if self._data[name].processor == "stm32" and self.opd[name].in_bootloader_mode:
                    next_state = C3NodeStatus.BOOTLOADER
                elif self._data[name].node_id != 0:  # aka CANopen nodes
                    next_state = self._check_co_nodes_state(name)
                else:
                    next_state = C3NodeStatus.ON
            elif status == C3OpdNodeStatus.DISABLED:
                next_state = C3NodeStatus.OFF

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
            last_state = node.status
            state = self._get_nodes_state(name)
            if self._loops != 0 and state != last_state:
                logger.info(f"node {name} state change {last_state.name} -> {state.name}")
            nodes_off += int(state == C3NodeStatus.OFF)
            nodes_booting += int(state == C3NodeStatus.BOOT)
            nodes_on += int(state == C3NodeStatus.ON)
            nodes_with_errors += int(state == C3NodeStatus.ERROR)
            nodes_not_found += int(state == C3NodeStatus.NOT_FOUND)
            nodes_dead += int(state == C3NodeStatus.DEAD)
            node.status = state

        self.node.od_write(C3Entry.NODE_MANAGER_NODES_OFF, nodes_off)
        self.node.od_write(C3Entry.NODE_MANAGER_NODES_BOOTING, nodes_booting)
        self.node.od_write(C3Entry.NODE_MANAGER_NODES_ON, nodes_on)
        self.node.od_write(C3Entry.NODE_MANAGER_NODES_WITH_ERRORS, nodes_with_errors)
        self.node.od_write(C3Entry.NODE_MANAGER_NODES_NOT_FOUND, nodes_not_found)
        self.node.od_write(C3Entry.NODE_MANAGER_NODES_DEAD, nodes_dead)

        if self.opd.status in [OpdState.DEAD, OpdState.DISABLED]:
            self._loops = -1
            return  # nothing to monitor

        if nodes_not_found == len(self._data):
            self._loops = 0

        # reset nodes with errors and probe for nodes not found
        for name, info in self._data.items():
            if info.opd_address == 0:
                continue

            if self._loops % 10 == 0 and self._data[name].status == C3NodeStatus.NOT_FOUND:
                self.opd[name].probe(True)

            if info.opd_always_on and info.status == C3NodeStatus.OFF:
                self.enable(name)

            if info.status == C3NodeStatus.DEAD and self.opd[name].is_enabled:
                self.opd[name].disable()  # make sure this is disabled
            elif info.status == C3NodeStatus.ERROR:
                logger.error(f"resetting node {name}, try {info.opd_resets + 1}")
                self.opd[name].reset(1)
                self._data[name].last_enable = monotonic()
                info.opd_resets += 1
            elif info.status in [C3NodeStatus.ON, C3NodeStatus.OFF]:
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

        if node.status != C3NodeStatus.OFF:
            logger.debug(f"cannot enable node {name} unless it is disabled")
            return

        if node.status == C3NodeStatus.DEAD:
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

        if node.status in [NodeStatus.OFF, C3NodeStatus.DEAD]:
            logger.debug(f"cannot disable node {name} as it is already disabled or dead")
            return

        if child_node:
            self.opd[node.child].disable()
        self.opd[name].disable()

    def node_status(self, name: Union[str, int]) -> C3NodeStatus:
        """Get the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        return self._data[name].status

    def _set_node_status(self, name: Union[str, int], state: int):
        """Set the status of a OreSat node."""

        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        if state == C3NodeStatus.ON:
            self.enable(name)
        elif state == C3NodeStatus.OFF:
            self.disable(name)
        elif state == C3NodeStatus.BOOTLOADER:
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
                if node.opd_address != 0 and node.status != C3NodeStatus.NOT_FOUND:
                    logger.info(f"node {name} state change {node.status.name} -> NOT_FOUND")
                    node.status = C3NodeStatus.NOT_FOUND
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
