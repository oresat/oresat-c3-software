from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum, unique
from time import monotonic

from loguru import logger
from oresat_cand import ManagerNodeClient, NodeState

from ..gen.c3_od import C3Entry
from ..gen.cards import Card, CardProcessor
from ..gen.missions import Mission
from ..subsystems.opd import Opd, OpdNode, OpdNodeState, OpdOctavoNode, OpdState, OpdStm32Node
from . import Service


@unique
class CardState(Enum):
    OFF = 0
    BOOT = 1
    ON = 2
    ERROR = 3
    NOT_FOUND = 4
    DEAD = 255


@dataclass
class Emcy:
    code: int
    info: int
    time: float


@dataclass
class CardData:
    opd_resets: int = 0
    last_enable: float = 0.0
    status: CardState = CardState.NOT_FOUND
    last_hb: float = 0.0
    hb_state: NodeState | None = None
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

    def __init__(self, node: ManagerNodeClient, mock_hw: bool = True):
        super().__init__(node)

        self.opd = Opd(
            self._NOT_ENABLE_PIN, self._NOT_FAULT_PIN, self._ADC_CURRENT_PIN, mock=mock_hw
        )

        sat_id = self.node.od_read(C3Entry.SATELLITE_ID)
        self.mission = Mission.from_id(sat_id)

        for card in self.mission.cards:
            if card.opd_address == 0:
                continue  # not an opd node

            if card.processor == CardProcessor.NONE:
                opd_node = OpdNode(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            elif card.processor == CardProcessor.STM32:
                opd_node = OpdStm32Node(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            elif card.processor == CardProcessor.OCTAVO:
                opd_node = OpdOctavoNode(self._I2C_BUS_NUM, card.name, card.opd_address, mock_hw)
            else:
                continue

            self.opd[card.opd_address] = opd_node

        self._data = {card: CardData() for card in self.mission.cards}
        self._loops = -1

        self.opd.enable()

        self.node.add_heartbeat_callback(self._hb_cb)
        self.node.add_emcy_callback(self._emcy_cb)

    def _hb_cb(self, node_id: int, state: NodeState):
        card = Card.from_node_id(node_id)
        self._data[card].hb_state = state
        self._data[card].last_hb = monotonic()

    def _emcy_cb(self, node_id: int, code: int, info: int):
        card = Card.from_node_id(node_id)
        emcy = Emcy(code, info, monotonic())
        self._data[card].emcys.append(emcy)

    def _check_co_cards_state(self, card: Card) -> CardState:
        node = self._data[card]
        next_state = node.status
        last_hb = self._data[card].last_hb

        if next_state == CardState.DEAD:
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                # if the node start sending heartbeats again (really only for flatsat)
                next_state = CardState.ON
            return next_state

        if card.processor == "stm32":
            timeout = self._STM32_BOOT_TIMEOUT
        else:
            timeout = self._OCTAVO_BOOT_TIMEOUT

        if self._data[card].last_enable + timeout > monotonic():
            if monotonic() > last_hb + self._RESET_TIMEOUT_S:
                next_state = CardState.BOOT
            else:
                next_state = CardState.ON
        elif node.status == CardState.ERROR:
            next_state = CardState.ERROR
        elif (
            self.node.od_read(C3Entry.FLIGHT_MODE)
            and self.node.bus_state == "NETWORK_UP"
            and monotonic() > (last_hb + self._RESET_TIMEOUT_S)
        ):
            logger.error(
                f"CANopen card {card.name} has had no heartbeats in {self._RESET_TIMEOUT_S} seconds"
            )
            next_state = CardState.ERROR
        else:
            next_state = CardState.ON

        return next_state

    def _get_cards_state(self, card: Card) -> CardState:
        # update status of data not on the OPD
        if card.opd_address == 0:
            if monotonic() > (self._data[card].last_hb + self._HB_TIMEOUT):
                next_state = CardState.OFF
            else:
                next_state = CardState.ON
            return next_state

        # opd subsystem is off
        if self.opd.status == OpdState.DISABLED:
            return CardState.NOT_FOUND

        prev_state = self._data[card].status

        # default is last state
        next_state = prev_state

        # update status of data on the OPD
        if self.opd.status == OpdState.DEAD:
            next_state = CardState.DEAD
        else:
            status = self.opd[card.opd_address].status
            if self._data[card].opd_resets >= self._MAX_CO_RESETS:
                next_state = CardState.DEAD
            elif status == OpdNodeState.FAULT:
                next_state = CardState.ERROR
            elif status == OpdNodeState.NOT_FOUND:
                next_state = CardState.NOT_FOUND
            elif status == OpdNodeState.ENABLED:
                if card.processor == "stm32" and self.opd[card.opd_address].in_bootloader_mode:
                    next_state = CardState.BOOTLOADER
                elif card.node_id != 0:  # aka CANopen cards
                    next_state = self._check_co_cards_state(card)
                else:
                    next_state = CardState.ON
            elif status == OpdNodeState.DISABLED:
                next_state = CardState.OFF

        return next_state

    def on_loop(self):
        """Monitor all OPD data and check that data that are on are sending heartbeats."""

        self._loops += 1
        self.sleep(1)

        cards_off = 0
        cards_booting = 0
        cards_on = 0
        cards_with_errors = 0
        cards_not_found = 0
        cards_dead = 0
        for card, data in self._data.items():
            last_state = data.status
            state = self._get_cards_state(card)
            if self._loops != 0 and state != last_state:
                logger.info(f"card {card.name} state change {last_state.name} -> {state.name}")
            cards_off += int(state == CardState.OFF)
            cards_booting += int(state == CardState.BOOT)
            cards_on += int(state == CardState.ON)
            cards_with_errors += int(state == CardState.ERROR)
            cards_not_found += int(state == CardState.NOT_FOUND)
            cards_dead += int(state == CardState.DEAD)
            data.status = state

        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_OFF, cards_off)
        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_BOOTING, cards_booting)
        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_ON, cards_on)
        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_WITH_ERRORS, cards_with_errors)
        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_NOT_FOUND, cards_not_found)
        self.node.od_write(C3Entry.NODE_MANAGER_CARDS_DEAD, cards_dead)

        if self.opd.status in [OpdState.DEAD, OpdState.DISABLED]:
            self._loops = -1
            return  # nothing to monitor

        if cards_not_found == len(self._data):
            self._loops = 0

        # reset cards with errors and probe for cards not found
        for card, data in self._data.items():
            if card.opd_address == 0:
                continue

            if self._loops % 10 == 0 and self._data[card].status == CardState.NOT_FOUND:
                self.opd[card.opd_address].probe(True)

            if card.opd_always_on and data.status == CardState.OFF:
                self.enable(card)

            if data.status == CardState.DEAD and self.opd[card.opd_address].is_enabled:
                self.opd[card.opd_address].disable()  # make sure this is disabled
            elif data.status == CardState.ERROR:
                logger.error(f"resetting card {card.name}, try {data.opd_resets + 1}")
                self.opd[card.opd_address].reset(1)
                self._data[card].last_enable = monotonic()
                data.opd_resets += 1
            elif data.status in [CardState.ON, CardState.OFF]:
                data.opd_resets = 0

    def enable(self, card: Card, bootloader_mode: bool = False):
        data = self._data[card]
        if card.opd_address == 0:
            logger.warning(f"cannot enable card {card.name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if data.status != CardState.OFF:
            logger.debug(f"cannot enable card {card.name} unless it is disabled")
            return

        if data.status == CardState.DEAD:
            logger.error(f"cannot enable card {card.name} as it is DEAD")
            return

        if card.processor == "stm32":
            self.opd[card.opd_address].enable(bootloader_mode)
            if card.child:
                self.opd[card.child.opd_address].enable(bootloader_mode)
        else:
            self.opd[card.opd_address].enable()
            if card.child:
                self.opd[card.child.opd_address].enable()
        data.last_enable = monotonic()

    def disable(self, card: Card):
        if card.opd_address == 0:
            logger.warning(f"cannot disable card {card.name} as it is not on the OPD")
            return  # not on OPD, nothing to do

        if self._data[card].status in [CardState.OFF, CardState.DEAD]:
            logger.debug(f"cannot disable card {card.name} as it is already disabled or dead")
            return

        if card.child:
            self.opd[card.child.opd_address].disable()
        self.opd[card.opd_address].disable()

    def status(self, card: Card) -> CardState:
        return self._data[card].status

    @property
    def status_json(self) -> str:
        tmp = []
        for card, data in self._data.items():
            tmp.append(
                {
                    "name": card.name,
                    "node_id": card.node_id,
                    "processor": card.processor,
                    "opd_addr": card.opd_address,
                    "status": data.status.name,
                }
            )
        return json.dumps(tmp)

    def _set_opd_status(self, value: int):
        if value == 0:
            self.opd.disable()
            for card, data in self._data.items():
                if card.opd_address != 0 and data.status != CardState.NOT_FOUND:
                    logger.info(f"card {card.name} state change {data.status.name} -> NOT_FOUND")
                    data.status = CardState.NOT_FOUND
        elif value == 1:
            if self.opd.status == OpdState.DISABLED:
                for data in self._data.values():
                    data.last_enable = monotonic()
            self.opd.enable()

    @property
    def uart_node(self) -> Card | None:
        return self._uart_node

    @uart_node.setter
    def uart_node(self, card: Card | None):
        if self._uart_node is not None:
            self.opd[self._uart_node].disable_uart()
        if card is not None:
            self.opd[card].enable_uart()
        self._uart_node = card
