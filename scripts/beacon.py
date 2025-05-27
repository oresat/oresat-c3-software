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

    print("loop | source->dest  |   LBand EDL seq   rej  Batt V1       V2")

    loop = 0
    while True:
        loop += 1
        raw = s.recv(4096)
        ax = ax25_unpack(raw)
        print(f"{loop:4} | {ax.src_callsign}->{ax.dest_callsign}", end="")

        crc = int.from_bytes(ax.payload[-4:], "little")
        if crc != crc32(ax.payload[:-4]):
            print(" | invalid CRC", end="")
        elif ax.payload[:3] != bytes("{{z", "ascii"):
            print(" | invalid payload header", ax.payload[:3], end="")
        else:
            lband_rx = int.from_bytes(ax.payload[22:26], "little")
            edl_seq = int.from_bytes(ax.payload[37:41], "little")
            edl_rej = int.from_bytes(ax.payload[41:45], "little")
            vbatt_1 = int.from_bytes(ax.payload[49:51], "little")
            vbatt_2 = int.from_bytes(ax.payload[81:83], "little")
            print(
                f" | {lband_rx:4} rx {edl_seq:6}# {edl_rej:4}× {vbatt_1:6}mV {vbatt_2:6}mV", end=""
            )
        if args.verbose:
            print("\n", raw.hex(), end="")
        print()


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        main()
