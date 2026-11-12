import argparse
from argparse import Namespace, _SubParsersAction
from pathlib import Path

import canopen
from canopen.objectdictionary import (
    BOOLEAN,
    DOMAIN,
    FLOAT_TYPES,
    INTEGER_TYPES,
    OCTET_STRING,
    UNICODE_STRING,
    VISIBLE_STRING,
)
from canopen.sdo import SdoArray, SdoRecord
from oresat_configs import Mission, OreSatConfig, __version__

STRING_TYPES = (VISIBLE_STRING, UNICODE_STRING)
BINARY_TYPES = (OCTET_STRING, DOMAIN)


class SDO_Manager:
    def __init__(self, oresat):
        # loading the configs is computationally slow so it must happen on init.
        self.config = OreSatConfig(oresat)

    def do_write_sdo(self, args: Namespace):
        """Send sdo
        Paramters:
            args:
                bus (str): name of the can bus
                node (str): name of remote node
                index (str): name of index to access
                subindex (str): name of subindex to access
                value (str): the value to send or the file path
        """
        remote_node = self.make_remote_node(args.node.lower())
        sdo = self.make_sdo(remote_node, args.index, args.subindex)

        # recast value
        value: int | bool | float | str | bytes

        # convert string input to correct data type
        if sdo.od.data_type == BOOLEAN:
            value = bool(args.value)
        elif sdo.od.data_type in INTEGER_TYPES:
            value = int(args.value, 0)
        elif sdo.od.data_type in FLOAT_TYPES:
            value = float(args.value)
        elif sdo.od.data_type == STRING_TYPES:
            value = args.value
        elif sdo.od.data_type in BINARY_TYPES:  # read in binary data from file
            file = Path(args.value)
            with file.open("rb") as f:
                value = f.read()

        # making a new network is computationally cheap
        network = canopen.Network()
        with network.connect(bustype="socketcan", channel=args.bus):
            network.add_node(remote_node)
            try:
                if sdo.od.data_type in BINARY_TYPES:
                    sdo.raw = value
                else:
                    sdo.phys = value
            except (canopen.SdoAbortedError, FileNotFoundError) as e:
                raise SystemExit(f"SDO failed: {e}") from None

    def do_read_sdo(self, args: Namespace) -> None:
        print("Not implemented yet.")
        return None

    def make_mode(self, args: Namespace) -> str | None:
        """Translate the mode to a standard mode"""
        mode = args.mode.lower()

        if mode in ["r", "read"]:
            return "read"

        if mode in ["w", "write"]:
            return "write"

        # TODO: if sdo is read only or write only, then select that by default
        print("Error, mode is not good.")
        return None

    def make_remote_node(self, node: str):
        """Make the node from the object dictionary"""
        # TODO: error catching
        return canopen.RemoteNode(0, self.config.od_db[node.lower()])

    def make_sdo(self, node: canopen.RemoteNode, index: str, subindex: str):
        """Make a SDO"""
        try:
            sdo = node.sdo[index]
            if isinstance(sdo, (SdoRecord, SdoArray)):
                sdo = sdo[subindex]
        except KeyError as e:
            print("Error: sdo could not be made.")
            print(e)
            return None

        return sdo

    def valid_args(self, args: Namespace) -> bool:
        """Check if args is valid"""

        # TODO: Check that the node is valid before checking index and subindex

        # Check that index and subindex are valid sdo is able to be made
        sdo = self.make_sdo(self.make_remote_node(args.node), args.index, args.subindex)
        if sdo is None:
            return False

        # Mode must be "r" or "w" or "read" or "write"
        mode = self.make_mode(args)
        if mode is None:
            return False

        return True

    def build_arguments(subparsers: _SubParsersAction) -> None:
        """Build command line arguments for this script.

        This function will be invoked by scripts.main to configure command line arguments for
        this subcommand. Use subparsers.add_parser() to get an ArgumentParser. The parser must
        have the default argument func which is the entry point for this
        subcommand: parser.set_defaults(func=?)

        Parameters
        ----------
        subparsers
            The output of ArgumentParser.add_subparsers() from the primary ArgumentParser.
            This function should call add_parser() on this parameter to get the
            ArgumentParser that is used to configure arguments for this subcommand.
            See https://docs.python.org/3/library/argparse.html#sub-commands, especially
            the end of that section, for more.
        """
        desc = "read or write value to a node's object dictionary via SDO transfers"
        parser = subparsers.add_parser("sdo", description=desc, help=desc)

        parser.add_argument("bus", metavar="BUS", help="CAN bus to use (e.g., can0, vcan0)")
        parser.add_argument(
            "node", metavar="NODE", help="device node name (e.g. gps, solar_module_1)"
        )
        parser.add_argument(
            "mode", metavar="MODE", help="r[ead] or w[rite] (e.g. r, read, w, write)"
        )
        parser.add_argument("index", metavar="INDEX", help="object dictionary index")
        parser.add_argument(
            "subindex", metavar="SUBINDEX", help='object dictionary subindex or "none"'
        )
        parser.add_argument(
            "value",
            metavar="VALUE",
            nargs="?",
            default="",
            help="Data to write or a path to a file containing  octet/domain data (e.g. data.bin).",
        )


if __name__ == "__main__":
    # TODO: add filename parser
    batch_parser = argparse.ArgumentParser(prog="oresat_configs_batch_parser")
    batch_parser.add_argument(
        "file",
        metavar="FILE",
        help="File of metadata and batch of oresat_configs commands, toml format.",
    )
    # add mission as part of the batch argument
    batch_parser.add_argument(
        "--oresat",
        default=Mission.default().arg,
        choices=[m.arg for m in Mission],
        type=lambda x: x.lower().removeprefix("oresat"),
        help="Oresat Mission. (Default: %(default)s)",
    )
    batch_args = batch_parser.parse_args()

    with open(batch_args.file, 'r') as fd:
        cmd_strings = fd.readlines()

    sdo_manager = SDO_Manager(batch_args.oresat)

    # TODO: make parser an attribute or function of sdo_manager
    cmd_parser = argparse.ArgumentParser(prog="oresat_configs_lite")
    cmd_parser.add_argument("--version", action="version", version="%(prog)s v" + __version__)
    cmd_parser.set_defaults(func=lambda _: cmd_parser.print_help())
    cmd_subparsers = cmd_parser.add_subparsers(title="subcommands")

    # This is temporarily a function of the class
    # this excludes the default sdo_transfer function and the mission argument
    # TODO: after making it an attribute of the instance,
    # extend defaults for arguments now that mission is known
    SDO_Manager.build_arguments(cmd_subparsers)

    cmd_args_list = []
    for cmd_str in cmd_strings:
        try:
            cmd_args = cmd_parser.parse_args(cmd_str.split())
        except Exception as e:
            print("Error parsing args")
            print(cmd_str)
            raise (e)
        try:
            sdo_manager.valid_args(cmd_args)
        except Exception as e:
            print("Parsed args are not valid")
            print(cmd_args)
            raise (e)

        cmd_args_list.append(cmd_args)

    # once all of the commands have been checked,
    # now actually do each command
    for cmd_args in cmd_args_list:
        print(cmd_args)
        mode = sdo_manager.make_mode(cmd_args)
        if mode == "read":
            sdo_manager.do_read_sdo(cmd_args)
        if mode == "write":
            sdo_manager.do_write_sdo(cmd_args)

    exit()
