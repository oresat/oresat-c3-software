#!/usr/bin/env python3
"""Listens for and prints C3 beacons"""


import os
import socket
import sys
from argparse import ArgumentParser
from contextlib import suppress
from zlib import crc32

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.ax25 import ax25_unpack


def main():
    parser = ArgumentParser("Receives and prints beacon packets")
    parser.add_argument(
        "-o", "--host", default="localhost", help="address to use, default is %(default)s"
    )
    parser.add_argument(
        "-u",
        "--beacon-port",
        default=10015,
        type=int,
        help="port to receive beacons on, default is %(default)s",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print out packet hex")
    args = parser.parse_args()

    host = args.host if args.host in ["localhost", "127.0.0.1"] else ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((host, args.beacon_port))

    loop = 0
    while True:
        loop += 1
        raw = s.recv(4096)
        ax = ax25_unpack(raw)
        print(f"{loop:4} | {ax.src_callsign}->{ax.dest_callsign}", end="")

        crc = int.from_bytes(ax.payload[-4:], "little")
        if crc != crc32(ax.payload[:-4]):
            print(" | invalid CRC", end="")

        if ax.payload[:3] != bytes("{{z", "ascii"):
            print(" | invalid payload header", ax.payload[:3], end="")
        print()

        if args.verbose:
            print(raw.hex())


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        main()
