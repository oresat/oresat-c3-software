#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

from __future__ import annotations

import os
import socket
import sys
from argparse import ArgumentParser
from cmd import Cmd
from dataclasses import astuple
from pathlib import Path
from time import time
from typing import Any

from oresat_configs import EdlCommandConfig, MissionConfig, load_edl_config

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.gen.edl_commands import (
    EDL_COMMANDS,
    EdlCommandId,
    EdlCommandRequest,
    EdlCommandResponse,
)
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


def str2value(string: str, data_type: str, enums: dict[str, int] | None = None) -> Any:
    """Conver raw string input from user to correct data type."""

    value: Any = string
    try:
        if data_type.startswith("bool"):
            if enums and string in enums:
                value = bool(enums[string])
            elif string.lower() in ["f", "false", "disable", "0", "off"]:
                value = False
            elif string.lower() in ["t", "true", "enable", "1", "on"]:
                value = True
            else:
                raise ValueError()
        elif data_type.startswith("int"):
            value = int(string)
        elif data_type.startswith("uint"):
            if enums and string in enums:
                value = enums[string]
            else:
                value = int(string, 16) if string.startswith("0x") else int(string)
        elif data_type.startswith("float"):
            value = float(string)
        elif data_type == "bytes":
            value = bytes.fromhex(string)
    except Exception as e:
        raise ValueError(f'value "{string}" cannot be convert to data type {data_type}') from e
    return value


def find_cmd(cmd_id: EdlCommandId, commands: list[EdlCommandConfig]) -> EdlCommandConfig | None:
    for c in commands:
        if c.id == cmd_id:
            return c
    return None


class EdlCommandShell(Cmd):
    """Edl command shell for testing."""

    intro = "Welcome to the EDL shell. Type help or ? to list commands.\n"
    prompt = "> "

    def __init__(
        self,
        oresat: float,
        host: str,
        uplink_port: int,
        downlink_port: int,
        hmac_key: bytes,
        seq_num: int,
        verbose: bool,
    ):
        super().__init__()

        config_path = Path(__file__).parent.parent / "configs/edl.yaml"
        oresat_str = f"oresat{oresat}".replace(".", "_")
        self._configs = {EdlCommandId(c.id).name: c for c in load_edl_config(config_path)}

        mission_config_path = Path(__file__).parent.parent / f"configs/{oresat_str}.yaml"
        mission = MissionConfig.from_yaml(mission_config_path)
        self._scid = mission.edl.spacecraft_id

        self._hmac_key = hmac_key
        self._timeout = 5
        self._seq_num = seq_num
        self._verbose = verbose

        self._uplink_address = (host, uplink_port)
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if host not in ["localhost", "127.0.0.1"]:
            host = ""

        self._downlink_address = (host, downlink_port)
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._downlink_socket.bind(self._downlink_address)
        self._downlink_socket.settimeout(self._timeout)

    def do_help(self, arg: str) -> None:
        args = arg.strip().lower().split(" ")

        if arg == "":
            print("commands:")
            for key in sorted([c for c in self._configs]):
                c = self._configs[key]
                print(f"  {c.name:20}: {c.description}")
            print("control:")
            print(f"  {'hmac':20}: set hmac (32 bytes)")
            print(f"  {'quit':20}: quit the shell")
            print(f"  {'sequence_number':20}: set sequence number")
            print(f"  {'timeout':20}: set response timeout (in seconds)")
            print(f"  {'verbose':20}: enable / disable printing raw packets")
        elif args[0].replace("-", "_").upper() in self._configs:
            cmd = args[0].replace("-", "_").upper()
            command = self._configs[cmd]
            print(f"description: {command.description} ")
            print(f"format: {cmd} " + " ".join([f"[{r.name}]" for r in command.request]))
            print("args:")
            for r in command.request:
                name = f"{r.name} ({r.data_type})"
                print(f"  {name:25}: {r.description}")
            if len(command.request) == 0:
                print(f"  {None}")
            print("returns:")
            for r in command.response:
                name = f"{r.name} ({r.data_type})"
                print(f"  {name:25}: {r.description}")
            if len(command.response) == 0:
                print(f"  {None}")
        else:
            print(f'ERROR: invalid command "{args[0]}". Type help or ? to list commands.')
        print()

    def _send_packet(self, code_name: str, args: tuple | None = None) -> tuple | None:
        print(f"Request {code_name}: {args} | seq_num: {self._seq_num}")

        res_packet = None
        try:
            cmd_id = EdlCommandId[code_name.upper()]
            command = EDL_COMMANDS[cmd_id]

            payload = command.request(*args) if args and command.request else None
            req_cmd = EdlCommandRequest(cmd_id.value, payload)

            req_packet = EdlPacket(self._scid, req_cmd, self._seq_num, SRC_DEST_ORESAT)
            req_packet_raw = req_packet.pack(self._hmac_key)

            self._uplink_socket.sendto(req_packet_raw, self._uplink_address)
            if self._verbose:
                print("SENT: " + req_packet_raw.hex())
            self._seq_num += 1

            if command.response is not None:
                res_packet_raw = self._downlink_socket.recv(1024)
                if res_packet_raw:
                    if self._verbose:
                        print("RECV: " + res_packet_raw.hex())
                    res_packet = EdlPacket.unpack(res_packet_raw, self._scid, self._hmac_key)
        except Exception as e:
            print(f"ERROR: {e}")
            return None

        ret = None
        if res_packet is not None:
            res: EdlCommandResponse = res_packet.payload
            res_cmd = astuple(res.payload) if res.payload else None
            print(f"Response {code_name}: {res_cmd}")
        else:
            print("Command has no response")

        return ret

    def _print_arg_num_error(self, cmd: str, expected_len: int, got_len: int) -> None:
        print(
            f'ERROR: invalid number of args for "{cmd.lower()}" command; expected '
            f"{expected_len} got {got_len}"
        )

    def do_verbose(self, line: str) -> None:
        args = line.strip().split(" ")
        if len(args) == 0:
            print(f"verbose is {self._verbose}")
        elif len(args) == 1:
            self._verbose = str2value(args[0], "bool")
        else:
            self._print_arg_num_error("verbose", 1, len(args))
        print()

    def do_timeout(self, line: str) -> None:
        args = line.strip().split(" ")
        if len(args) == 0:
            print(f"timeout is {self._timeout} seconds")
        elif len(args) == 1:
            self._timeout = str2value(args[0], "uint32")
            self._downlink_socket.settimeout(self._timeout)
        else:
            self._print_arg_num_error("timeout", 1, len(args))
        print()

    def do_hmac(self, line: str) -> None:
        args = line.strip().split(" ")
        if len(args) == 0:
            print(f"hmac is {self._hmac_key.hex()}")
        elif len(args) == 1:
            if len(args[0]) == 64:
                self._hmac = str2value(args[0], "bytes")
            else:
                print("ERROR: invalid hmac, must be hex string of 32 bytes")
        else:
            self._print_arg_num_error("hmac", 1, len(args))
        print()

    def do_sequence_number(self, line: str) -> None:
        args = line.strip().split(" ")
        if len(args) == 0:
            print(f"sequence_number is {self._seq_num}")
        elif len(args) == 1:
            self._seq_num = str2value(args[0], "uint32")
        else:
            self._print_arg_num_error("sequence_number", 1, len(args))
        print()

    def default(self, line: str) -> bool | None:
        if line.lower() in ["q", "quit", "exit"]:
            return True  # used to exit shell

        args = line.strip().split(" ")
        cmd = args[0].upper()
        args = args[1:] or []

        try:
            if cmd in self._configs:
                command = self._configs[cmd]

                # override to for current time
                if cmd.lower() == "rtc_set_time" and (len(args) == 0 or args[0] == "now"):
                    args = [str(int(time()))]

                if len(command.request) == len(args):
                    req_args = [
                        str2value(arg, req_field.data_type)
                        for req_field, arg in zip(command.request, args)
                    ]
                    self._send_packet(command.name, tuple(req_args))
                else:
                    self._print_arg_num_error(cmd.lower(), len(command.request), len(args))
            else:
                print(f'ERROR: invalid command "{cmd.lower()}". Type help or ? to list commands.')
            print()
        except Exception as e:
            print(f"ERROR: {e}\n")
        return False


def main() -> None:
    """Main for EDL shell script"""
    parser = ArgumentParser("Send a EDL command via socket")
    parser.add_argument(
        "-o",
        "--oresat",
        default=0.5,
        type=float,
        choices=[0, 0.5, 1],
        help="oresat mission number (default: %(default)s)",
    )
    parser.add_argument(
        "-H", "--host", default="localhost", help="address to use (default: %(default)s)"
    )
    parser.add_argument(
        "-u",
        "--uplink-port",
        default=10025,
        type=int,
        help="port to use for the uplink (default: %(default)s)",
    )
    parser.add_argument(
        "-d",
        "--downlink-port",
        default=10016,
        type=int,
        help="port to use for the downlink (default: %(default)s)",
    )
    parser.add_argument(
        "-n",
        "--sequence-number",
        type=int,
        default=0,
        help="edl sequence number (default: %(default)s)",
    )
    parser.add_argument(
        "-m",
        "--hmac",
        default="",
        help="edl hmac, must be 32 bytes (default is all zeros)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print raw packets")
    args = parser.parse_args()

    if args.hmac:
        if len(args.hmac) != 64:
            print("Invalid hmac, must be hex string of 32 bytes")
            sys.exit(1)
        else:
            hmac_key = bytes.fromhex(args.hmac)
    else:
        hmac_key = b"\x00" * 32

    shell = EdlCommandShell(
        args.oresat,
        args.host,
        args.uplink_port,
        args.downlink_port,
        hmac_key,
        args.sequence_number,
        args.verbose,
    )

    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        pass

    print(f"last sequence number: {shell._seq_num}")


if __name__ == "__main__":
    main()
