"""All base classes for modes."""

import json
import os
import struct
from dataclasses import dataclass
from enum import Enum, unique
from threading import Event
from time import monotonic
from typing import ClassVar, Optional, Union

from olaf import MasterNode, logger

from ..services.node_manager import NodeManagerService, NodeState


class ModeError(Exception):
    """Base Error/Exception for mode errors"""


@unique
class ModeState(Enum):
    STANDBY = 0
    SETUP = 1
    RUNNING = 2
    TEARDOWN = 3
    ERROR = 0xFF


@dataclass
class ModeArgs:
    """
    All child classes MUST override _BYTES_FMT with the correct struct fmt str.

    See https://docs.python.org/3/library/struct.html#format-characters for the struct fmt strs.
    """

    _BYTES_FMT: ClassVar[str] = ""

    @classmethod
    def validate(cls, args: bytes) -> bool:
        return struct.calcsize(cls._BYTES_FMT) == len(args)

    @classmethod
    def from_bytes(cls, args: bytes):
        return cls(*struct.unpack(cls._BYTES_FMT, args))


class Mode:
    """
    Base OreSat Mode class.

    All child classes can override `on_*` methods.
    """

    ARGS = None
    REQUIRED_CARDS: Optional[list[str]] = None

    def __init__(self, mode_args: ModeArgs, node: MasterNode, node_manager: NodeManagerService):

        self.mode_args = mode_args
        self.node: MasterNode = node
        self.node_manager = node_manager
        self.start_time = 0.0
        self._event = Event()
        self.state: Union[int, Enum] = 0

    def on_setup(self):
        """Setup for node. Will be called before the start_time to allow do any setup."""

        pass

    def on_run(self):
        """
        On the method for the mode. Will be called at the start_time.
        """

        pass

    def on_error(self, error: Exception):
        logger.error(str(error))

    def sleep_ms(self, milliseconds: float):
        self._event.wait(milliseconds / 1000)

    def enable_nodes(self, nodes: list[str], timeout: int = 60):
        """
        Enable multiple node and block until the nodes are alive on the CAN bus.

        Parameters
        ----------
        nodes: list[str]
            List of nodes to enable
        timeout: int
            Timeout to block until giving up.

        Raises
        ------
        TimeoutError
            One or more nodes did are not alive on CAN bus after timeout.
        """

        for node in nodes:
            self.node_manager[node].enable()

        tic = monotonic()
        while not self.are_nodes_online(nodes):
            if tic + timeout > monotonic():
                raise TimeoutError("not all enabled nodes came online")
            self.sleep_ms(500)

    def are_nodes_online(self, nodes: list[str]) -> bool:
        """Check to see if any all nodes are online."""

        on = 0
        for node in nodes:
            if self.node_manager[node].status == NodeState.ON:
                on += 1
        return on == len(nodes)

    def are_any_nodes_dead(self, nodes: list[str]) -> bool:
        """Check to see if any nodes are dead."""

        dead = 0
        for node in nodes:
            if self.node_manager[node].status == NodeState.ON:
                dead += 1
        return dead != len(nodes)

    def olaf_file_list(self, card: str, cache: str) -> list[str]:
        """Get the list of files from one of olaf file caches a octavo card."""

        if cache not in ["feaad", "fwrite"]:
            raise ValueError("cache arg must be fread or fwrite")

        json_str = self.node.sdo_read(card, f"{cache}_cache", "length")
        return json.dumps(json_str)

    def olaf_fwrite(self, card: str, file_path: str):
        """Write a file to a octavo card."""

        self.node.sdo_write(card, "fwrite_cache", "file_name", os.path.basename(file_path))
        with open(file_path, "rb") as f:
            raw = f.read()
        self.node.sdo_write(card, "fwrite_cache", "file_data", raw)

    def olaf_fread(self, card: str, file_name: str, dir_path: str = "/tmp") -> str:
        """Read a file from a octavo card."""

        file_path = f"{dir_path}/{file_name}"
        self.node.sdo_write(card, "fwrite_cache", "file_name", file_name)
        raw = self.node.sdo_read(card, "fwrite_cache", "file_data")
        with open(file_path, "wb") as f:
            f.write(raw)
        return file_path
