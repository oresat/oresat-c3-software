import json
import socket
import sys
from argparse import ArgumentParser
from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Union

from _opd import Opd, OpdStm32Node
from loguru import logger
from oresat_configs import Card, OreSatConfig


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
            ON --> UPDATING : Flasher started
            UPDATING --> BOOT : Flasher finished (rebooting)
            UPDATING --> OFF : Disable
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
    UPDATING = 6
    """Node is currently receiving a firmware update."""
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
    is_updating: bool = field(init=False, default=False)
    """Whether the node is currently being updated."""


class OPD_Manager:
    # opd hardware constants
    _NOT_ENABLE_PIN = "OPD_nENABLE"
    _NOT_FAULT_PIN = "OPD_nFAULT"
    _ADC_CURRENT_PIN = 2
    _I2C_BUS_NUM = 2

    def __init__(self, cards, *, mock_hw=False):

        # create OPD database
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

        # go ahead and enable it
        self.opd.enable()

    def node_info(self, name: Union[str, int]) -> dict:
        """Get information about node"""
        if isinstance(name, int):
            name = self.opd_addr_to_name[name]

        node = self._data[name]
        logger.debug(f"Node Info {node}")
        return node.info.__dict__

    def probe(self, name: Union[str, int], reset: bool = False) -> None:
        """Probe a given node, and maybe reset it"""
        try:
            opd_node = self.opd[name]
        except KeyError:
            logger.warning(f"OPD {name} not found.")
            return
        logger.debug(f"Probing node {name}")
        logger.debug(f"Reset set to {reset}")
        logger.debug(opd_node.probe(reset=reset))

    def scan(self):
        return self.opd.scan()

    def status(self):
        # reset nodes with errors and probe for nodes not found
        status_dict = {}
        for name, node in self._data.items():
            try:
                opd_node = self.opd[name]
            except KeyError:
                continue

            # status_dict[name] = node.status.name
            status_dict[name] = opd_node.status.name

        return status_dict

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
        logger.info(f"Enabling node {name}")
        opd = self.opd[name]
        opd_child = self.opd[node.info.child] if node.info.child else None
        if isinstance(opd, OpdStm32Node):
            logger.debug("Node is an STM32 Node")
            opd.enable(bootloader_mode=bootloader_mode)
            if isinstance(opd_child, OpdStm32Node):
                opd_child.enable(bootloader_mode=bootloader_mode)
            elif opd_child:
                opd_child.enable()
        else:
            opd.enable()
            if opd_child:
                opd_child.enable()

        logger.info(f"Done enabling node {name}")

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

        if child_node:
            self.opd[node.info.child].disable()
        self.opd[name].disable()


def print_dictionary(target):
    print(json.dumps(target, default=lambda o: '<not serializable>', indent=2))


if __name__ == "__main__":
    opd_parser = ArgumentParser("OPD_CLI", add_help=True)
    opd_parser.add_argument("-v", "--verbose", action="store_true", help="enable verbose logging")
    opd_parser.add_argument("-m", "--mock", action="store_true", help="mock run this script")
    opd_parser.add_argument("-s", "--satellite", default="ORESAT1", help="satellite mission to use")
    opd_parser.add_argument(
        "-i", "--ip", default="127.0.0.1", help="host IP address to use (defaults to 127.0.0.1)"
    )
    opd_parser.add_argument(
        "-p", "--port", type=int, default=9000, help="port number to use (defaults to 9000)"
    )

    args = opd_parser.parse_args()

    # Set up the logger
    logger.remove()
    logger.add(sys.stdout, level=("DEBUG" if args.verbose else "INFO"))

    # Get the configs for this satellite mission
    config = OreSatConfig(args.satellite)

    # Create the OPD object
    try:
        opd_manager = OPD_Manager(config.cards, mock_hw=args.mock)
    except Exception as e:
        logger.error("Error occured when creating the OPD object.")
        logger.error("You may need to pass the `-m` or `--mock` flag.")
        raise e

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((args.ip, args.port))
        s.listen()
        stay_up = True
        while stay_up:
            logger.info("Waiting for new connection...")
            conn, addr = s.accept()
            with conn:
                logger.debug(f"Connected by {addr}")
                while True:
                    data = conn.recv(1024)
                    logger.debug("Recieved data")
                    logger.debug(f"{data}")

                    if not data:
                        break

                    # expect json
                    request = json.loads(data.decode('utf-8'))
                    payload = ""
                    if not ("cmd" in request.keys() and "nodes" in request.keys()):
                        print("Request does not have the correct keys")
                        continue

                    match request["cmd"]:
                        case "print":
                            logger.info("Doing the print command")
                            # clean cards argument
                            # only do cards that exist
                        case "status":
                            logger.info("Doing the status command")
                            print(opd_manager.opd._status)
                            print_dictionary(opd_manager.status())
                        case "scan":
                            logger.info("Doing the scan command")
                            print(opd_manager.opd.scan())

                        case "reset":
                            logger.info("Doing the reset command")
                            node_list = set(request["nodes"])
                            if len(node_list) == 0:
                                # do all nodes
                                logger.debug("No list of nodes given")
                                node_list = opd_manager.node_id_to_name.values()
                                logger.debug("Adding all nodes")
                            for node in node_list:
                                logger.info(f"Resetting node {node}")
                                # if node is not in
                                opd_manager.probe(node, reset=True)
                            # probe all

                        case "probe":
                            logger.info("Doing the probe command")
                            node_list = set(request["nodes"])
                            if len(node_list) == 0:
                                # do all nodes
                                logger.debug("No list of nodes given")
                                node_list = opd_manager.node_id_to_name.values()
                                logger.debug("Adding all nodes")
                            for node in node_list:
                                logger.info(f"Probing node {node}")
                                # if node is not in
                                opd_manager.probe(node)
                            # probe all

                        case "enable":
                            logger.info("Doing the enable command")
                            node_list = set(request["nodes"])
                            for node in node_list:
                                logger.info(f"Enabling node {node}")
                                # if node is not in
                                opd_manager.enable(node)
                        case "disable":
                            logger.info("Doing the disable command")
                            node_list = set(request["nodes"])
                            for node in node_list:
                                logger.info(f"Disabling node {node}")
                                # if node is not in
                                opd_manager.disable(node)
                        case "end":
                            logger.info("About to end the server...")
                            stay_up = False

                    # send info back to confirm
                    result = {"status": "Done", "payload": ""}
                    conn.sendall((json.dumps(result)).encode('utf-8'))
                logger.debug("Disconnection detected, client probably finished transaction.")
        # Exited main loop
        logger.info("Ending server")
