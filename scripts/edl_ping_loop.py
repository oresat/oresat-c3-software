#!/usr/bin/env python3
"""Sends EDL ping commands continuously, tracking responses"""

import os
import socket
import sys
from argparse import ArgumentParser
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Generator, Optional, Union

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket


class Timeout:
    """Tracks how long to sleep until the start of the next loop iteration.

    The idea is we'd like to wait until a specific time but the timer only accepts durations
    and may wake up early. This class turns an absolute time (given in loops) into a relative
    duration from now and makes it easy to resume the timer if woken up early. Should be created
    close (in time) to the start of the loop.

    Parameters
    ----------
    delay: duration in seconds of one loop iteration
    """

    def __init__(self, delay: float):
        self.start = monotonic()
        self.delay = delay

    def next(self, loop: int) -> Generator[float, None, None]:
        """Generates a monotonically decreasing series of timeouts for the given loop iteration.

        Parameters
        ----------
        loop: non-negative int giving the current loop iteration
        """

        while (t := self.delay * loop + self.start - monotonic()) > 0:
            yield t


class Link:
    """Manages sending and receiving pings, tracking various stats in the process

    Parameters
    ----------
    host: address to send pings to, either an IP or a hostname
    up_port: port on host to send to
    down_port: local port to listen on
    sequence_number: EDL sequence number to start on
    hmac: EDL HMAC key
    """

    def __init__(self, host: str, up_port: int, down_port: int, sequence_number: int, hmac: bytes):
        self._uplink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._uplink.connect((host, up_port))

        self._downlink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._downlink.bind((host if host in ["localhost", "127.0.0.1"] else "", down_port))

        self.sent = 0
        self.echo = 0
        self.sequence_number = sequence_number
        self.hmac = hmac
        self.sent_times: OrderedDict[int, float] = OrderedDict()
        self.last = 0

    def send(self, request: EdlCommandRequest) -> bytes:
        self.sequence_number = self.sequence_number + 1 & 0xFFFF_FFFF
        message = EdlPacket(request, self.sequence_number, SRC_DEST_ORESAT).pack(self.hmac)
        self._uplink.send(message)
        return message

    def ping(self, value: int) -> bytes:
        if not value > self.last:
            raise ValueError("value must be monotonically increasing")
        self.last = value
        message = self.send(EdlCommandRequest(EdlCommandCode.PING, (value,)))
        self.sent_times[value] = monotonic()
        self.sent += 1
        return message

    def beacon_ping(self) -> bytes:
        return self.send(EdlCommandRequest(EdlCommandCode.BEACON_PING, None))

    @dataclass(frozen=True)
    class Invalid:
        """Return type for an abnormal ping response with value 'payload' and content 'raw'.

        This could be caused by abnormal conditions (udp reorder/duplicate, bugs in c3, multiple
        c3s responding, ...)
        """

        payload: int
        raw: bytes

    @dataclass(frozen=True)
    class Lost:
        """Return type indicating that 'count' pings have been dropped"""

        count: int

    @dataclass(frozen=True)
    class Recv:
        """Return type for a successful ping response with latency 'delay' and content 'raw'"""

        delay: float
        raw: bytes

    Result = Union[Invalid, Lost, Recv]

    def recv(self, timeout: Generator[float, None, None]) -> Generator[Result, None, None]:
        for t in timeout:
            self._downlink.settimeout(t)
            response = self._downlink.recv(4096)
            payload = EdlPacket.unpack(response, self.hmac).payload.values[0]
            t_recv = monotonic()

            # self.sent_times.keys() are monotonic (not to be confused with the timestamps from
            # the monotonic() clock) but not necessarily contiguous.
            if payload not in self.sent_times:
                yield self.Invalid(payload, response)
                continue

            lost = 0
            while self.sent_times:
                value, t_sent = self.sent_times.popitem(last=False)
                if payload == value:
                    break
                lost += 1

            if lost > 0:
                yield self.Lost(lost)
            self.echo += 1
            yield self.Recv(t_recv - t_sent, response)

    def rate(self):
        return 100 * self.echo // self.sent


def ping_loop(link: Link, timeout: Timeout, count: int, beacon: Optional[int], verbose: bool):
    print("Loop | Seqn  Sent  [ Recv (Rate) Latency or Lost×]", end="", flush=True)
    loop = 0
    while count < 0 or loop < count:
        loop += 1
        print(f"\n{loop:4} |", end="", flush=True)

        try:
            if beacon is None or loop % beacon:
                message = link.ping(loop)
                print(f"{link.sequence_number:4}# {link.sent:4}↖  ", end="", flush=True)
            else:
                message = link.beacon_ping()
                print(f"{link.sequence_number:4}# BECN↖  ", end="", flush=True)
            if verbose:
                print("\n↖", message.hex())
        except ConnectionRefusedError:
            print("Connection Refused: Uplink destination not available to receive packets")
            continue

        try:
            for result in link.recv(timeout.next(loop)):
                if isinstance(result, Link.Recv):
                    print(
                        f"[{link.echo:4}↙ ({link.rate():3}%)",
                        f"{int(result.delay * 1000):4}ms]",
                        end="",
                        flush=True,
                    )
                    if verbose:
                        print("\n↙", result.raw.hex())
                elif isinstance(result, Link.Lost):
                    print(f"[      ({link.rate():3}%) {result.count:4}× ]", end="", flush=True)
                elif isinstance(result, Link.Invalid):
                    print(
                        f"[{link.echo:4}↙ ({link.rate():3}%)",
                        f"Unexpected payload {result.payload}, expected {loop}]",
                    )
                    if verbose:
                        print("\n↙", result.raw.hex())
        except socket.timeout:
            pass


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
    parser.add_argument(
        "-c",
        "--count",
        default=-1,
        type=int,
        help="send up to COUNT pings before stopping. Negative values are forever",
    )
    parser.add_argument(
        "-b",
        "--beacon-ping",
        action='store_const',
        const=30,
        help="Send a beacon ping every %(const)s normal pings",
    )

    args = parser.parse_args()

    if args.loop_delay < 0:
        print(f"Invalid delay {args.loop_delay}, must be >= 0")
        return

    if args.beacon_ping is not None and args.beacon_ping <= 0:
        print(f"Invalid beacon ping interval {args.beacon_ping}, must be > 0")
        return

    if args.hmac:
        if len(args.hmac) != 64:
            print("Invalid hmac, must be hex string of 32 bytes")
            return
        hmac_key = bytes.fromhex(args.hmac)
    else:
        hmac_key = bytes(32)

    link = Link(args.host, args.uplink_port, args.downlink_port, args.sequence_number, hmac_key)
    timeout = Timeout(args.loop_delay / 1000)

    try:
        ping_loop(link, timeout, args.count, args.beacon_ping, args.verbose)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nNext sequence number:", link.sequence_number)


if __name__ == "__main__":
    main()
