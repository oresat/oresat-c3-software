#!/usr/bin/env python3
"""Quick shell to manually send EDL commands."""

import os
import socket
import sys
from argparse import ArgumentParser
from time import monotonic, sleep, time

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


class Timeout:
    """Tracks how long to sleep until the start of the next loop iteration.

    Waiting for a response packet may return early so there's multiple calls
    that need to know the time until the next cycle.
    """

    def __init__(self, delay):
        self.start = monotonic()
        self.delay = delay

    def next(self, loop):
        return max(self.start + self.delay * loop - monotonic(), 0)


def ping_loop(
    seq_num: int,
    uplink: socket.socket,
    downlink: socket.socket,
    timeout: Timeout,
    hmac_key: bytes,
    verbose: bool,
):
    loop = 0
    sent = 0
    recv = 0

    while True:
        sleep(timeout.next(loop))
        loop += 1
        seq_num += 1
        seq_num &= 0xFF_FF_FF_FF

        request = EdlCommandRequest(EdlCommandCode.PING, (loop,))
        message = EdlPacket(request, seq_num, SRC_DEST_ORESAT).pack(hmac_key)
        if verbose:
            print("-->", message.hex())

        print(f"Seqnum: {seq_num:4} | Loop {loop:4} | ", end="", flush=True)
        try:
            uplink.send(message)
            last_ts = time()
            sent += 1
        except ConnectionRefusedError:
            print("Connection Refused: Upstream not available to receive packets")
            continue

        print(f"Sent: {sent:4} | ", end="", flush=True)

        downlink.settimeout(timeout.next(loop))
        try:
            response = downlink.recv(4096)
        except socket.timeout:
            print("(timeout)")
            continue
        timediff = int((time() - last_ts) * 1000)

        payload = EdlPacket.unpack(response, hmac_key).payload.values[0]
        if payload != loop:
            print(f"Unexpected payload {payload}, expected {loop}")
        else:
            recv += 1
            rate = 100 - ((sent - recv) * 100) // sent
            print(f"PING: {payload} | Recv: {recv:4} | {timediff:4} ms | Return: {rate}%")

        if verbose:
            print("<==", response.hex())


def main():
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

    if args.loop_delay < 0:
        print(f"Invalid delay {args.loop_delay}, must be >= 0")
        return

    if args.hmac:
        if len(args.hmac) != 64:
            print("Invalid hmac, must be hex string of 32 bytes")
            return
        hmac_key = bytes.fromhex(args.hmac)
    else:
        hmac_key = bytes(32)

    downlink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    downlink_host = args.host if args.host in ["localhost", "127.0.0.1"] else ""
    downlink.bind((downlink_host, args.downlink_port))

    uplink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uplink.connect((args.host, args.uplink_port))

    timeout = Timeout(args.loop_delay / 1000)

    try:
        ping_loop(args.sequence_number, uplink, downlink, timeout, hmac_key, args.verbose)
    except KeyboardInterrupt:
        print()  # ctrl-c has a good chance of happening during a parial line


if __name__ == "__main__":
    main()
