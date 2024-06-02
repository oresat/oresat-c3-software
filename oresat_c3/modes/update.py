"""Updatec mode."""

import struct
from dataclasses import dataclass
from enum import Enum, unique
from time import monotonic
from typing import ClassVar

from olaf import NodeStop, UpdaterState, logger

from ..services.node_manager import NodeState
from ._mode import Mode, ModeArgs


@unique
class UpdateModeState(Enum):
    STANDBY = 0
    UPDATING = 1
    REBOOT = 2
    HEARTBEAT_CHECK = 3
    CANCELLED = 4
    SUCCESSIFUL = 5
    FAILURE = 6
    ERROR = 0xFF


@unique
class UpdateMethod(Enum):
    CAN = 0
    """All nodes support updating over CAN."""
    UART = 1
    """stm32 nodes on the OPD only."""


@dataclass
class UpdateModeArgs(ModeArgs):

    _BYTES_FMT: ClassVar[str] = "<2B"
    node_id: float
    """uint8: The node id of the card to update."""
    update_method: int
    """uint8: The update method. See `:py:class:UpdateMethod`"""
    file_name: str
    """str: Name of the file on the C3 to update with."""

    @classmethod
    def validate(cls, args: bytes) -> bool:
        return struct.calcsize(cls._BYTES_FMT) < len(args)

    @classmethod
    def from_bytes(cls, args: bytes):
        size = struct.calcsize(cls._BYTES_FMT)
        args_list = struct.unpack(cls._BYTES_FMT, args[:size])
        args_list += (args[size:].decode(),)
        return cls(*args_list)


class UpdateMode(Mode):
    """Update a card mode."""

    ARGS = UpdateModeArgs

    def on_setup(self):

        card = self.node.od_db[self.mode_args.node_id]
        self.enable_nodes([card])
        self.state = UpdateModeState.STANDBY

    def on_run(self):

        card = self.node.od_db[self.mode_args.node_id]
        if card.processor == "octavo":
            if self.node.od.node_id == 0x1:
                self._update_c3()
            else:
                self._update_octavo(card)
        elif card.processor == "stm32":
            if self.mode_args.update_method == UpdateMethod.CAN.value:
                self._update_stm32_over_can(card)
            elif self.mode_args.update_method == UpdateMethod.UART.value:
                self._update_stm32_over_uart(card)
            else:
                ValueError("unknown update method")

    def _update_c3(self):

        logger.info("starting update for C3")
        self.node.od_write("updater", "update", True)
        self.state = UpdateModeState.UPDATING

        while True:
            update_status = self.node.od_read("updater", "status")
            if update_status == UpdaterState.PRE_UPDATE_FAILED.value:
                self.state = UpdateModeState.CANCELLED
                break
            elif update_status == UpdaterState.UPDATE_SUCCESSFUL.value:
                logger.info("update for C3 has completed")
                self.state = UpdateModeState.SUCCESSIFUL
                break
            elif update_status == UpdaterState.UPDATE_FAILED.value:
                self.state = UpdateModeState.FAILURE
                break
            self.sleep_ms(1000)

        if self.state == UpdateModeState.SUCCESSIFUL:
            self.node.stop(NodeStop.SOFT_RESET)

    def _update_octavo(self, card: str):

        logger.info(f"starting update for {card}")
        self.node.sdo_write(card, "updater", "update", True)
        self.state = UpdateModeState.UPDATING

        while True:
            update_status = self.node.od_read(card, "updater_status")
            if update_status == UpdaterState.PRE_UPDATE_FAILED.value:
                logger.error(f"update for {card} failed its pre-updatae check")
                self.state = UpdateModeState.CANCELLED
                return
            elif update_status == UpdaterState.UPDATE_SUCCESSFUL.value:
                logger.info(f"update for {card} has completed")
                self.node.sdo_write(card, "updater", "make_status_file", True)
                self.state = UpdateModeState.SUCCESSIFUL
                break
            elif update_status == UpdaterState.UPDATE_FAILED.value:
                logger.critical(f"update for {card} failed")
                self.state = UpdateModeState.FAILURE
                return
            self.sleep_ms(1000)

        self.node_manager.restart(self.mode_args.node_id)
        self.state = UpdateModeState.HEARTBEAT_CHECK.value

        timeout = 60
        if self.node_manager.status[self.mode_args.node_id].status == NodeState.ON:
            self.state = UpdateModeState.SUCCESSIFUL
        elif monotonic() - self.start_time > timeout:
            self.state = UpdateModeState.FAILURE.value

    def _update_stm32_over_uart(self, card: str):
        pass

    def _update_stm32_over_can(self, card: str):
        pass
