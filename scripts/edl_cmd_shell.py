#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from cmd import Cmd
from typing import Any, Optional

from oresat_configs import OreSatConfig, OreSatId

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket

EDL_CMD_DEFS = OreSatConfig(OreSatId.ORESAT0_5).edl_cmd_defs
EDL_CMD_NAMESs = [c.name for c in EDL_CMD_DEFS.values()]


def str2value(string: str, data_type: str, enums: dict[str, int] = {}) -> Any:
    """Conver raw string input from user to correct data type."""

    value: Any = string
    try:
        if data_type.startswith("bool"):
            if string in enums:
                value = bool(enums[string])
            elif string.lower() == "false":
                value = False
            else:
                value = bool(string.lower() == "true" or int(string))
        elif data_type.startswith("int"):
            value = int(string)
        elif data_type.startswith("uint"):
            if string in enums:
                value = enums[string]
            else:
                value = int(string, 16) if string.startswith("0x") else int(string)
        elif data_type.startswith("float"):
            value = float(string)
        elif data_type == "bytes":
            value = bytes.fromhex(string)
    except Exception as e:  # pylint: disable=W0718
        raise ValueError(f'value "{string}" cannot be convert to data type {data_type}') from e
    return value


class EdlCommandShell(Cmd):
    """Edl command shell for testing."""

    intro = "Welcome to the EDL shell. Type help or ? to list commands.\n"
    prompt = "> "

    def __init__(
        self, host: str, uplink_port: int, downlink_port: int, hmac_key: bytes, seq_num: int
    ):
        super().__init__()

        self.configs = OreSatConfig(OreSatId.ORESAT0_5)
        self._hmac_key = hmac_key
        self._timeout = 5
        self._seq_num = seq_num

        self._uplink_address = (host, uplink_port)
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        if host not in ["localhost", "127.0.0.1"]:
            host = ""

        self._downlink_address = (host, downlink_port)
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._downlink_socket.bind(self._downlink_address)
        self._downlink_socket.settimeout(self._timeout)

    def do_help(self, arg: str):
        args = arg.strip().lower().split(" ")

        if arg == "":
            print("commands:")
            for c in EDL_CMD_DEFS.values():
                print(f"  {c.name:20}: {c.description}")
            print("control:")
            print(f"  {'quit':20}: quit the shell")
        elif args[0].replace("-", "_") in EDL_CMD_DEFS.names():
            cmd = args[0].replace("-", "_")
            command = EDL_CMD_DEFS[cmd]
            print(f"description: {command.description} ")
            print(f"format: {cmd} " + " ".join([f"[{r.name}]" for r in command.request]))
            print("args:")
            for r in command.request:
                name = f"{r.name} ({r.data_type})"
                print(f"  {name:25}: {r.description}")
                if r.enums:
                    print(f"    enums: {r.enums}")
            print("returns:")
            for r in command.response:
                name = f"{r.name} ({r.data_type})"
                print(f"  {name:25}: {r.description}")
                if r.enums:
                    print(f"    enums: {r.enums}")
        else:
            print(f'ERROR: invalid command "{args[0]}". Type help or ? to list commands.')
        print()

    def _send_packet(self, code_name: str, args: Optional[tuple]) -> Optional[tuple]:
        print(f"Request {code_name}: {args} | seq_num: {self._seq_num}")

        res_packet = None
        try:
            cmd_def = EDL_CMD_DEFS[code_name]

            # make packet
            req_raw = cmd_def.uid.to_bytes(1, "little")
            req_raw += cmd_def.encode_request(args)
            req_packet = EdlPacket(req_raw, self._seq_num, SRC_DEST_ORESAT)
            req_packet_raw = req_packet.pack(self._hmac_key)

            # send request
            self._uplink_socket.sendto(req_packet_raw, self._uplink_address)

            if len(cmd_def.response) > 0:
                # recv response
                res_packet_raw = self._downlink_socket.recv(1024)
                # parse respone
                res_packet = EdlPacket.unpack(res_packet_raw, self._hmac_key)
            self._seq_num += 1
        except Exception as e:  # pylint: disable=W0718
            print(f"ERROR: {e}")
            return None

        ret = None
        if res_packet is not None and len(res_packet.payload) > 1:
            ret = cmd_def.decode_response(res_packet.payload[1:])
            print(f"Response {code_name}: {ret}")
        elif len(cmd_def.response) == 0:
            print("Command has no response")

        return ret

    def default(self, line: str):

        if line in ["q", "quit"]:
            return True

        args = line.strip().split(" ")
        cmd = args[0].lower()
        args = args[1:] or []

        try:
            if cmd in EDL_CMD_NAMESs:
                command = EDL_CMD_DEFS[cmd]
                if len(command.request) == len(args):
                    req_args = [
                        str2value(arg, req_field.data_type, req_field.enums)
                        for req_field, arg in zip(command.request, args)
                    ]
                    self._send_packet(command.name, tuple(req_args))
                else:
                    print(
                        f'ERROR: invalid number of args for "{cmd}" command; expected '
                        f"{len(command.request)} got {len(args)}"
                    )
            else:
                print(f'ERROR: invalid command "{cmd}". Type help or ? to list commands.')
            print()
        except Exception as e:  # pylint: disable=W0718
            print(f"ERROR: {e}\n")
        return False


def main():
    """Main for EDL shell script"""
    parser = ArgumentParser("Send a EDL command via socket")
    parser.add_argument(
        "-o", "--host", default="localhost", help="address to use, default is localhost"
    )
    parser.add_argument(
        "-u",
        "--uplink-port",
        default=10025,
        type=int,
        help="port to use for the uplink, default is 10025",
    )
    parser.add_argument(
        "-d",
        "--downlink-port",
        default=10016,
        type=int,
        help="port to use for the downlink, default is 10016",
    )
    parser.add_argument(
        "-n",
        "--sequence-number",
        type=int,
        default=0,
        help="edl sequence number, default 0",
    )
    parser.add_argument(
        "-m",
        "--hmac",
        default="",
        help="edl hmac, must be 32 bytes, default all zero",
    )
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
        args.host, args.uplink_port, args.downlink_port, hmac_key, args.sequence_number
    )

    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        pass

    print(f"last sequence number: {shell._seq_num}")  # pylint: disable=W0212


if __name__ == "__main__":
    main()
