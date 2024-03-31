#!/usr/bin/env python3
"""
File upload to OreSat.
"""

import os
import random
import signal
import socket
import sys
import time
from argparse import ArgumentParser
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Lock, Thread
from typing import Any

from cfdppy import CfdpState, PacketDestination, get_packet_destination
from cfdppy.handler.dest import DestHandler
from cfdppy.handler.source import SourceHandler
from cfdppy.mib import (
    CheckTimerProvider,
    DefaultFaultHandlerBase,
    IndicationCfg,
    LocalEntityCfg,
    RemoteEntityCfg,
    RemoteEntityCfgTable,
)
from cfdppy.request import PutRequest
from cfdppy.user import (
    CfdpUserBase,
    FileSegmentRecvdParams,
    MetadataRecvParams,
    TransactionFinishedParams,
    TransactionId,
    TransactionParams,
)
from olaf import OreSatFile
from spacepackets.cfdp import CfdpLv
from spacepackets.cfdp.defs import ChecksumType, ConditionCode, TransmissionMode
from spacepackets.cfdp.tlv import ProxyPutRequest, ProxyPutRequestParams
from spacepackets.countdown import Countdown
from spacepackets.seqcount import SeqCountProvider
from spacepackets.util import ByteFieldU8

from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket

sys.path.insert(0, os.path.abspath(".."))


class PrintFaults(DefaultFaultHandlerBase):
    """Prints all faults to stdout"""

    def notice_of_suspension_cb(self, transaction_id, cond, progress):
        print(f"Transaction {transaction_id} suspended: {cond}. Progress {progress}")

    def notice_of_cancellation_cb(self, transaction_id, cond, progress):
        print(f"Transaction {transaction_id} cancelled: {cond}. Progress {progress}")

    def abandoned_cb(self, transaction_id, cond, progress):
        print(f"Transaction {transaction_id} abandoned: {cond}. Progress {progress}")

    def ignore_cb(self, transaction_id, cond, progress):
        print(f"Transaction {transaction_id} ignored: {cond}. Progress {progress}")


class PrintUser(CfdpUserBase):
    """Prints all indications to sdtout"""

    def transaction_indication(self, transaction_indication_params: TransactionParams):
        print(f"Indication: Transaction. {transaction_indication_params}")

    def eof_sent_indication(self, transaction_id: TransactionId):
        print(f"Indication: EOF Sent for {transaction_id}.")

    def transaction_finished_indication(self, params: TransactionFinishedParams):
        print(f"Indication: Transaction Finished. {params}")

    def metadata_recv_indication(self, params: MetadataRecvParams):
        print(f"Indication: Metadata Recv. {params}")

    def file_segment_recv_indication(self, params: FileSegmentRecvdParams):
        print(f"Indication: File Segment Recv. {params}")

    def report_indication(self, transaction_id: TransactionId, status_report: Any):
        print("Indication: Report for {transaction_id}. {status_report}")

    def suspended_indication(self, transaction_id: TransactionId, cond_code: ConditionCode):
        print("Indication: Suspended for {transaction_id}. {cond_code}")

    def resumed_indication(self, transaction_id: TransactionId, progress: int):
        print("Indication: Resumed for {transaction_id}. {progress}")

    def fault_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        print("Indication: Fault for {transaction_id}. {cond_code}. {progress}")

    def abandoned_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        print("Indication: Abandoned for {transaction_id}. {cond_code}. {progress}")

    def eof_recv_indication(self, transaction_id: TransactionId):
        print("Indication: EOF Recv for {transaction_id}")


class Uplink(Thread):
    """Manages the Uplink socketand queue.

    Separate from Source/Dest so that multiple handlers can share
    the socket.
    """

    def __init__(self, address, hmac_key, sequence_number, bad_connection, delay):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.queue = SimpleQueue()
        self._address = address
        self._hmac_key = hmac_key
        self._sequence_number = sequence_number
        self._bad_connection = bad_connection
        self._delay = delay

    def run(self):
        uplink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        uplink.connect(self._address)

        while True:
            payload = self.queue.get()
            if self._bad_connection and not random.randrange(5):
                continue  # simulate dropped packets
            print("--->", payload)
            packet = EdlPacket(payload, self._sequence_number, SRC_DEST_ORESAT)
            message = packet.pack(self._hmac_key)
            uplink.send(message)
            self._sequence_number += 1
            time.sleep(self._delay)


class Downlink(Thread):
    """Manages the downlink socket and queue

    Separate from Source/Dest so that multiple handlers can
    share the socket.
    """

    def __init__(self, address, hmac_key, bad_connection):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.source_queue = SimpleQueue()
        self.dest_queue = SimpleQueue()
        self._address = address
        self._hmac_key = hmac_key
        self._bad_connection = bad_connection

    def run(self):
        downlink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        downlink.bind(self._address)

        while True:
            message = downlink.recv(4096)
            if self._bad_connection and not random.randrange(5):
                continue  # simulate dropped packets
            packet = EdlPacket.unpack(message, self._hmac_key, True).payload
            print("<---", packet)

            if get_packet_destination(packet) == PacketDestination.DEST_HANDLER:
                self.dest_queue.put(packet)
            else:
                self.source_queue.put(packet)


class CountdownProvider(CheckTimerProvider):
    """Copied from the cfdppy example.

    I think this is to allow for custom timeouts based on latency between local and remote
    entities? It doesn't set all the timers though, ACK timer I'm looking at you.
    """

    def provide_check_timer(self, local_entity_id, remote_entity_id, entity_type) -> Countdown:
        return Countdown(timedelta(seconds=5.0))


class Source(Thread):
    """Responsible for running a SourceHandler statemachine"""

    def __init__(self, uplink, downlink, localcfg, remote_entities):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.uplink = uplink
        self.downlink = downlink

        self.src = SourceHandler(
            cfg=localcfg,
            user=PrintUser(),
            remote_cfg_table=remote_entities,
            check_timer_provider=CountdownProvider(),
            seq_num_provider=SeqCountProvider(16),
        )

        self.lock = Lock()

    def run(self):
        while packet := self.downlink.get():
            with self.lock:
                self.src.insert_packet(packet)
                self.src.state_machine()
                while self.src.packets_ready:
                    pdu = self.src.get_next_packet().pdu
                    self.uplink.put(pdu)

    def send_packets(self, put):
        """Sends a PutRequest to the uplink and handles respones.

        blocks.
        """
        assert self.src.put_request(put)
        self.src.state_machine()

        while True:
            with self.lock:
                while self.src.packets_ready:
                    pdu = self.src.get_next_packet().pdu
                    self.uplink.put(pdu)
                self.src.state_machine()

            print(self.src.step)
            if self.src.state == CfdpState.IDLE:
                break

            if not self.src.packets_ready:
                time.sleep(0.5)


class Dest(Thread):
    """Responsible for running a DestHandler statemachine"""

    def __init__(self, uplink, downlink, localcfg, remote_entities):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.uplink = uplink
        self.downlink = downlink

        self.dest = DestHandler(
            cfg=localcfg,
            user=PrintUser(),
            remote_cfg_table=remote_entities,
            check_timer_provider=CountdownProvider(),
        )

    def run(self):
        while True:
            try:
                packet = self.downlink.get_nowait()
                self.dest.insert_packet(packet)
            except Empty:
                time.sleep(0.1)
            self.dest.state_machine()
            while self.dest.packets_ready:
                pdu = self.dest.get_next_packet().pdu
                self.uplink.put(pdu)


def main():
    """Upload a file to the satellite."""
    parser = ArgumentParser()
    parser.add_argument("file_path")
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
        "-r",
        "--random-data",
        type=int,
        default=0,
        help="generate random file data of a given length",
    )
    parser.add_argument(
        "-b", "--bad-connection", action="store_true", help="simulate a bad connection"
    )
    parser.add_argument(
        "-l", "--loop-delay", type=int, default=50, help="upload loop delay in milliseconds"
    )
    parser.add_argument(
        "-n",
        "--sequence-number",
        type=int,
        default=0,
        help="edl sequence number, default 0",
    )
    parser.add_argument("-s", "--buffer-size", type=int, default=950, help="file data buffer size")
    parser.add_argument(
        "-m",
        "--hmac",
        default="",
        help="edl hmac, must be 32 bytes, default all zero",
    )
    parser.add_argument(
        "-p",
        "--proxy",
        action="store_true",
        help="Initiate a proxy put request instead of a normal one",
    )
    args = parser.parse_args()

    file_path = args.file_path.split("/")[-1]
    try:
        OreSatFile(file_path)
    except ValueError:
        print("file name must be in card-name_key_unix-time.extension format")
        print("example: c3_test_123.txt")
        sys.exit(1)

    if args.random_data:
        with open(args.file_path, mode="xb") as f:
            f.write(random.randbytes(args.random_data))

    if args.hmac:
        if len(args.hmac) != 64:
            print("Invalid hmac, must be hex string of 32 bytes")
            sys.exit(1)
        else:
            hmac_key = bytes.fromhex(args.hmac)
    else:
        hmac_key = bytes(32)

    uplink_address = (args.host, args.uplink_port)

    downlink_host = args.host if args.host in ["localhost", "127.0.0.1"] else ""
    downlink_address = (downlink_host, args.downlink_port)

    delay = args.loop_delay / 1000
    up = Uplink(uplink_address, hmac_key, args.sequence_number, args.bad_connection, delay)
    up.start()
    down = Downlink(downlink_address, hmac_key, args.bad_connection)
    down.start()

    SOURCE_ID = ByteFieldU8(0)
    DEST_ID = ByteFieldU8(1)

    localcfg = LocalEntityCfg(
        local_entity_id=SOURCE_ID,
        indication_cfg=IndicationCfg(),
        default_fault_handlers=PrintFaults(),
    )

    remote_entities = RemoteEntityCfgTable(
        [
            RemoteEntityCfg(
                entity_id=DEST_ID,
                max_file_segment_len=None,
                max_packet_len=args.buffer_size,
                closure_requested=False,
                crc_on_transmission=False,
                default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                crc_type=ChecksumType.CRC_32,
            ),
        ]
    )

    source = Source(up.queue, down.source_queue, localcfg, remote_entities)
    source.start()
    dest = Dest(up.queue, down.dest_queue, localcfg, remote_entities)
    dest.start()

    if args.proxy:
        put = PutRequest(
            destination_id=DEST_ID,
            source_file=None,
            dest_file=None,
            trans_mode=None,
            # FIXME: upstream bug - DestHandler does not respect closure_requested=None when
            # trans_mode defaults to ACKNOWLEGED
            closure_requested=True,
            msgs_to_user=[
                ProxyPutRequest(
                    ProxyPutRequestParams(
                        SOURCE_ID,
                        source_file_name=CfdpLv(args.file_path.encode()),
                        dest_file_name=CfdpLv(args.file_path.encode()),
                    )
                ).to_generic_msg_to_user_tlv()
            ],
        )
    else:
        put = PutRequest(
            destination_id=DEST_ID,
            source_file=Path(args.file_path),
            dest_file=Path(args.file_path),
            trans_mode=None,
            closure_requested=None,
        )

    source.send_packets(put)
    signal.pause()


if __name__ == "__main__":
    main()
