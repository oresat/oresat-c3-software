#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from cmd import Cmd
from time import time
from typing import Any, Union

import canopen
from oresat_configs import OreSatConfig, OreSatId

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EDL_COMMANDS, EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


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

    def _send_packet(self, code: EdlCommandCode, args: Union[tuple, None] = None) -> tuple:
        print(f"Request {code.name}: {args} | seq_num: {self._seq_num}")

        res_packet = None
        try:
            # make packet
            req = EdlCommandRequest(code, args)
            req_packet = EdlPacket(req, self._seq_num, SRC_DEST_ORESAT)
            req_packet_raw = req_packet.pack(self._hmac_key)

            # send request
            self._uplink_socket.sendto(req_packet_raw, self._uplink_address)

            edl_command = EDL_COMMANDS[code]
            if edl_command.res_fmt is not None or edl_command.res_unpack_func is not None:
                # recv response
                res_packet_raw = self._downlink_socket.recv(1024)
                # parse respone
                res_packet = EdlPacket.unpack(res_packet_raw, self._hmac_key)
            self._seq_num += 1
        except Exception as e:  # pylint: disable=W0718
            print(e)
            return tuple()

        if res_packet and res_packet.payload.values:
            ret = res_packet.payload.values
            print(f"Response {code.name}: {ret}")

        return ret

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

    def help_sdo_read(self):
        """Print help message for sdo_read command."""
        print("sdo_read <node> <index> <subindex>")
        print("  <node> is the node id or node name")
        print("  <index> is the index or object name")
        print("  <subindex> is the subindex or object name")

    def do_sdo_read(self, arg: str):
        """Do the sdo_read command."""

        args = arg.split(" ")
        if len(args) != 3:
            self.help_sdo_read()
            return

        node_id = None
        index = None
        subindex = None

        if args[0].startswith("0x"):
            node_id = int(args[0], 16)
            for i in self.configs.cards:
                if node_id == i.node_id:
                    name = i
                    break
        elif args[0] in self.configs.cards:
            name = args[0]
            node_id = self.configs.cards[args[0]].node_id
        else:
            print("invalid node arg")
            return

        od = self.configs.od_db[name]

        if args[1].startswith("0x"):
            index = int(args[1], 16)
        else:
            try:
                index = od[args[1]].index
            except Exception:  # pylint: disable=W0718
                print("invalid index arg")
                return

        if args[2].startswith("0x"):
            subindex = int(args[2], 16)
        else:
            try:
                if isinstance(od[index], canopen.objectdictionary.Variable):
                    subindex = 0
                else:
                    subindex = od[args[1]][args[2]].subindex
            except Exception:  # pylint: disable=W0718
                print("invalid subindex arg")
                return

        respone = self._send_packet(EdlCommandCode.CO_SDO_READ, (node_id, index, subindex))

        if not respone:
            return

        if respone[0] != 0:
            print(f"SDO error code: 0x{respone[0]:08X}")
            return

        if isinstance(od[index], canopen.objectdictionary.Variable):
            obj = od[index]
        else:
            obj = od[index][subindex]
        value = obj.decode_raw(respone[2])
        print("Value from SDO read: ", value)

    def help_sdo_write(self):
        """Print help message for sdo_write command."""
        print("sdo_write <node> <index> <subindex> <value>")
        print("  <node> is the node id or node name")
        print("  <index> is the index or object name")
        print("  <subindex> is the subindex or object name")
        print("  <value> is value to write")

    def do_sdo_write(self, arg: str):
        """Do the sdo_write command."""

        args = arg.split(" ")
        if len(args) != 4:
            self.help_sdo_write()
            return

        node_id = None
        index = None
        subindex = None

        if args[0].startswith("0x"):
            node_id = int(args[0], 16)
            for i in self.configs.cards:
                if node_id == i.node_id:
                    name = i
                    break
        elif args[0] in self.configs.cards:
            name = args[0]
            node_id = self.configs.cards[args[0]].node_id
        else:
            print("invalid node arg")
            return

        od = self.configs.od_db[name]

        if args[1].startswith("0x"):
            index = int(args[1], 16)
        else:
            try:
                index = od[args[1]].index
            except Exception:  # pylint: disable=W0718
                print("invalid index arg")
                return

        if args[2].startswith("0x"):
            subindex = int(args[2], 16)
        else:
            try:
                if isinstance(od[index], canopen.objectdictionary.Variable):
                    subindex = 0
                else:
                    subindex = od[args[1]][args[2]].subindex
            except Exception:  # pylint: disable=W0718
                print("invalid subindex arg")
                return

        if isinstance(od[index], canopen.objectdictionary.Variable):
            obj = od[index]
        else:
            obj = od[index][subindex]

        value: Any = None
        if obj.data_type == canopen.objectdictionary.BOOLEAN:
            value = args[3].lower() == "true"
        elif obj.data_type in canopen.objectdictionary.INTEGER_TYPES:
            value = int(args[3], 16) if args[3].startswith("0x") else int(args[3])
        elif obj.data_type in canopen.objectdictionary.FLOAT_TYPES:
            value = float(args[3])
        elif obj.data_type == canopen.objectdictionary.VISIBLE_STRING:
            value = args[3]
        else:
            print("invaid")
            return

        raw = obj.encode_raw(value)
        respone = self._send_packet(
            EdlCommandCode.CO_SDO_WRITE, (node_id, index, subindex, len(raw), raw)
        )

        if respone and respone[0] != 0:
            print(f"SDO error code: 0x{respone[0]:08X}")

    def help_c3_soft_reset(self):
        """Print help message for c3_soft_reset command."""
        print("c3_soft_reset")
        print("  no args")

    def do_c3_soft_reset(self, _):
        """Do the c3_soft_reset command."""

        self._send_packet(EdlCommandCode.C3_SOFT_RESET, None)

    def help_c3_hard_reset(self):
        """Print help message for c3_hard_reset command."""
        print("c3_hard_reset")
        print("  no args")

    def do_c3_hard_reset(self, _):
        """Do the c3_hard_reset command."""

        self._send_packet(EdlCommandCode.C3_HARD_RESET, None)

    def help_c3_factory_reset(self):
        """Print help message for c3_factory_reset command."""
        print("c3_factory_reset")
        print("  no args")

    def do_c3_factory_reset(self, _):
        """Do the c3_factory_reset command."""

        self._send_packet(EdlCommandCode.C3_FACTORY_RESET, None)

    def help_opd_sysenable(self):
        """Print help message for opd_sysenable command."""
        print("opd_sysenable <enable>")
        print("  <enable> is 0, 1, true, false")

    def do_opd_sysenable(self, arg: str):
        """Do the opd_sysenable command."""

        arg = arg.lower()
        if arg in ["true", "1"]:
            enable = True
        elif arg in ["false", "0"]:
            enable = False
        else:
            self.help_opd_sysenable()
            return

        self._send_packet(EdlCommandCode.OPD_SYSENABLE, (enable,))

    def help_opd_enable(self):
        """Print help message for opd_enable command."""
        print("opd_enable <name> <enable>")
        print("  <name> is the name of card or opd address in hex")
        print("  <enable> is 0, 1, true, false")

    def do_opd_enable(self, arg: str):
        """Do the opd_enable command."""

        args = arg.split(" ")
        if len(args) != 2:
            self.help_opd_sysenable()
            return

        if args[0].startswith("0x"):
            opd_addr = int(args[0], 16)
        else:
            opd_addr = 0
            for name, card in self.configs.cards.items():
                if name == args[0]:
                    opd_addr = card.opd_address
                    break
            if opd_addr == 0:
                print("invalid name / address")
                self.help_opd_enable()
                return

        arg1 = args[1].lower()
        if arg1 in ["true", "1"]:
            enable = True
        elif arg1 in ["false", "0"]:
            enable = False
        else:
            print("invalid enable value")
            self.help_opd_enable()
            return

        self._send_packet(EdlCommandCode.OPD_ENABLE, (opd_addr, enable))

    def help_rtc_set_time(self):
        """Print help message for rtc_set_time command."""
        print("rtc_set_time <number>")
        print(
            "  where <number> is unix time in seconds or the word 'now' to use the local system "
            "time"
        )

    def do_rtc_set_time(self, arg: str):
        """Do the rtc_set_time command."""

        args = arg.split(" ")
        if len(args) != 1:
            self.help_rtc_set_time()
            return

        arg0 = args[0]
        if arg0 in ["", "now"]:
            value = int(time())
        else:
            value = int(arg0)

        self._send_packet(EdlCommandCode.RTC_SET_TIME, (value,))


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
