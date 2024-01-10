#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from threading import Thread
from time import monotonic, sleep, time

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket

sent = 0
recv = 0
loop = 0
last_ts = {}


def send_thread(address: tuple, hmac_key: bytes, seq_num: int, delay: float, verbose: bool):
    """Send ping thread"""
    global sent  # pylint: disable=W0603
    global loop  # pylint: disable=W0603
    uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start_time = monotonic()

    while True:
        loop += 1
        seq_num += 1
        seq_num &= 0xFF_FF_FF_FF

        values = (loop,)
        print(f"Request PING: {values} | seq_num: {seq_num}")

        try:
            req = EdlCommandRequest(EdlCommandCode.PING, values)
            req_packet = EdlPacket(req, seq_num, SRC_DEST_ORESAT)
            req_message = req_packet.pack(hmac_key)

            if verbose:
                print(req_message.hex())

            uplink_socket.sendto(req_message, address)
            last_ts[loop] = time()
            for i in last_ts:
                if i > loop + 10:
                    del last_ts[loop]
            sent += 1
        except Exception:  # pylint: disable=W0718
            pass

        if delay > 0:
            sleep(delay - ((monotonic() - start_time) % delay))

        print(f"Sent: {sent} | Recv: {recv} | Return: {100 - ((sent - recv) * 100) // sent}%\n")


def main():
    """Loop EDL ping for testing."""
    global recv  # pylint: disable=W0603

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
    parser.add_argument("-v", "--verbose", action="store_true", help="print out packet hex")
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

    uplink_address = (args.host, args.uplink_port)

    downlink_host = args.host if args.host in ["localhost", "127.0.0.1"] else ""
    downlink_address = (downlink_host, args.downlink_port)
    downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    downlink_socket.bind(downlink_address)
    downlink_socket.settimeout(1)

    t = Thread(
        target=send_thread,
        args=(uplink_address, hmac_key, args.sequence_number, args.loop_delay / 1000, args.verbose),
        daemon=True,
    )
    t.start()

    while True:
        try:
            res_message = downlink_socket.recv(0xFF_FF)
            if args.verbose:
                print(res_message.hex())

            res_packet = EdlPacket.unpack(res_message, hmac_key)
            recv += 1

            timediff = -1.0
            if loop in last_ts:
                timediff = time() - last_ts[loop]
            print(f"Response PING: {res_packet.payload.values} | {int(timediff * 1000)} ms")
        except KeyboardInterrupt:
            break
        except Exception:  # pylint: disable=W0718
            continue


if __name__ == "__main__":
    main()
