#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from time import monotonic, sleep, time

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EDL_COMMANDS, EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


def main():
    """Loop EDL ping for testing."""

    parser = ArgumentParser("Send a EDL ping in a loop")
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
        "-l", "--loop-delay", type=int, default=1000, help="delay between loops in milliseconds"
    )
    args = parser.parse_args()

    hmac_key = b"\x00" * 32
    timeout = 5
    seq_num = 0
    start_time = monotonic()

    uplink_address = (args.host, args.uplink_port)
    uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    downlink_address = (args.host, args.downlink_port)
    downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    downlink_socket.bind(downlink_address)
    downlink_socket.settimeout(timeout)

    delay = args.loop_delay / 1000
    while True:
        sleep(delay - ((monotonic() - start_time) % delay))

        values = (int(time()),)
        print(f"Request PING: {values}")

        res_packet = None
        try:
            # make packet
            req = EdlCommandRequest(EdlCommandCode.PING, values)
            req_packet = EdlPacket(req, seq_num, SRC_DEST_ORESAT)
            req_packet_raw = req_packet.pack(hmac_key)
            print(req_packet_raw.hex())

            # send request
            uplink_socket.sendto(req_packet_raw, uplink_address)

            if EDL_COMMANDS[EdlCommandCode.PING].res_fmt is not None:
                # recv response
                res_packet_raw = downlink_socket.recv(1024)
                print(res_packet_raw.hex())

                # parse respone
                res_packet = EdlPacket.unpack(res_packet_raw, hmac_key)
        except Exception as e:  # pylint: disable=W0718
            print(e)
            return

        print(f"Response PING: {res_packet.payload.values}")


if __name__ == "__main__":
    main()
