#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from cmd import Cmd
from time import time
from typing import Union

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EDL_COMMANDS, EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


class EdlCommandShell(Cmd):
    """Edl command shell for testing."""

    intro = "Welcome to the EDL shell. Type help or ? to list commands.\n"
    prompt = "> "

    def __init__(self, host: str, uplink_port: int, downlink_port: int):
        super().__init__()

        self._hmac_key = b"\x00" * 32
        self._timeout = 5
        self._seq_num = 0

        self._uplink_address = (host, uplink_port)
        self._uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._downlink_address = (host, downlink_port)
        self._downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._downlink_socket.bind(self._downlink_address)
        self._downlink_socket.settimeout(self._timeout)

    def _send_packet(self, code: EdlCommandCode, args: Union[tuple, None] = None):
        print(f"Request {code.name}: {args}")

        res_packet = None
        try:
            # make packet
            req = EdlCommandRequest(code, args)
            req_packet = EdlPacket(req, self._seq_num, SRC_DEST_ORESAT)
            req_packet_raw = req_packet.pack(self._hmac_key)
            print(req_packet_raw.hex())

            # send request
            self._uplink_socket.sendto(req_packet_raw, self._uplink_address)

            if EDL_COMMANDS[code].res_fmt is not None:
                # recv response
                res_packet_raw = self._downlink_socket.recv(1024)
                print(res_packet_raw.hex())

                # parse respone
                res_packet = EdlPacket.unpack(res_packet_raw, self._hmac_key)
        except Exception as e:  # pylint: disable=W0718
            print(e)
            return

        if res_packet:
            print(f"Response {code.name}: {res_packet.payload.values}")
        else:
            print(f"Response {code.name}: None")

    def help_tx_control(self):
        """Print help message for tx control command."""
        print("tx_control <bool>")
        print("  where <bool> is to disable or enable tx. Supports true/false/1/0")

    def do_tx_control(self, arg: str):
        """Do the tx control command."""

        args = arg.split(" ")
        if not arg or len(args) != 1:
            self.help_tx_control()
            return

        arg0 = args[0].lower()
        if arg0 in ["true", "1"]:
            value = True
        elif arg0 in ["false", "0"]:
            value = False
        else:
            self.help_tx_control()
            return

        self._send_packet(EdlCommandCode.TX_CTRL, (value,))

    def help_beacon_ping(self):
        """Print help message for beacon ping command."""
        print("beacon_ping")
        print("  no args")

    def do_beacon_ping(self, _):
        """Do the beacon ping command."""

        self._send_packet(EdlCommandCode.BEACON_PING, None)

    def help_ping(self):
        """Print help message for ping command."""
        print("ping <number>")
        print("  where <number> is a uint32 number or the word 'time' for a unix timestamp")

    def do_ping(self, arg: str):
        """Do the ping command."""

        args = arg.split(" ")
        if len(args) != 1:
            self.help_ping()
            return

        arg0 = args[0]
        if arg0 in ["", "time"]:
            value = int(time())
        elif arg0.startswith("0x"):
            value = int(arg0, 16)
        else:
            value = int(arg0)

        self._send_packet(EdlCommandCode.PING, (value,))

    def help_rx_test(self):
        """Print help message for rx_test command."""
        print("rx_test")
        print("  no args")

    def do_rx_test(self, _):
        """Do the rx_test command."""

        self._send_packet(EdlCommandCode.RX_TEST, None)


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
    args = parser.parse_args()

    shell = EdlCommandShell(args.host, args.uplink_port, args.downlink_port)

    try:
        shell.cmdloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
