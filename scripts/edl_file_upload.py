#!/usr/bin/env python3
"""
File upload to OreSat.

Order of PDUs:
  - [send] metadata
  - loop:
      - [send] data transfer
      - [recv] possible nak
  - [send] EOF
  - [recv] EOF ack
  - [recv] Finished
  - [send] Finished ack
"""

import os
import random
import socket
import sys
import zlib
from argparse import ArgumentParser
from enum import IntEnum, auto
from threading import Event, Thread
from time import sleep

from olaf import OreSatFile
from spacepackets.cfdp import CrcFlag
from spacepackets.cfdp.conf import LargeFileFlag, PduConfig
from spacepackets.cfdp.defs import ChecksumType, ConditionCode, Direction, TransmissionMode
from spacepackets.cfdp.pdu import (
    AckPdu,
    DirectiveType,
    EofPdu,
    FinishedPdu,
    MetadataParams,
    MetadataPdu,
    NakPdu,
    TransactionStatus,
)
from spacepackets.cfdp.pdu.file_data import FileDataParams, FileDataPdu
from spacepackets.util import ByteFieldU8

sys.path.insert(0, os.path.abspath(".."))

from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlPacket

recv_queue = []
HMAC_KEY = b"\x00" * 32


def recv_thread(address: tuple, bad_connection: bool, event: Event):
    """Thread to receive packets from the satellite and put them into the queue."""

    edl_downlink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    edl_downlink_socket.bind(address)
    edl_downlink_socket.settimeout(0.1)

    loop_num = 0
    while not event.is_set():
        loop_num += 1

        try:
            res_message, _ = edl_downlink_socket.recvfrom(0xFFFFF)
        except socket.timeout:
            continue

        if bad_connection and loop_num % random.randint(1, 5):
            continue  # simulate dropped packets

        try:
            packet = EdlPacket.unpack(res_message, HMAC_KEY, True)
            recv_queue.append(packet.payload)
        except Exception as e:  # pylint: disable=W0718
            print(e)


class Indication(IntEnum):
    """CFDP Indications"""

    NONE = 0  # not an actually Indication, just a flag
    TRANSACTION = auto()
    EOF_SENT = auto()
    TRANSACTION_FINISHED = auto()
    METADATA = auto()
    FILE_SEGMENT_RECV = auto()
    REPORT = auto()
    SUSPENDED = auto()
    RESUMED = auto()
    FAULT = auto()
    ABANDONED = auto()
    EOF_RECV = auto()


class GroundEntity:
    """Ground station entity for file uploads."""

    PDU_CONF = PduConfig(
        transaction_seq_num=ByteFieldU8(0),
        trans_mode=TransmissionMode.ACKNOWLEDGED,
        source_entity_id=ByteFieldU8(0),
        dest_entity_id=ByteFieldU8(0),
        file_flag=LargeFileFlag.NORMAL,
        crc_flag=CrcFlag.NO_CRC,
        direction=Direction.TOWARDS_RECEIVER,
    )

    def __init__(self, file_name: str, file_data: bytes, buffer_size: int):
        self.f = None
        self.offset = 0
        self.file_name = file_name
        self.file_data = file_data
        self.file_data_len = len(file_data)
        self.last_indication = Indication.NONE
        self.got_eof_ack = False
        self.buffer_size = buffer_size

    def loop(self):
        """Entity loop"""

        res_pdu = None
        req_pdu = None

        while len(recv_queue) > 0:
            res_pdu = recv_queue.pop()
            if isinstance(res_pdu, NakPdu):
                print("recv nak")
                self.offset = res_pdu.end_of_scope
                self.last_indication = Indication.TRANSACTION
            elif isinstance(res_pdu, AckPdu):
                self.got_eof_ack = True
                print("recv ack")
                self.last_indication = Indication.TRANSACTION_FINISHED

        if self.last_indication in [Indication.NONE, Indication.TRANSACTION]:
            self.last_indication = Indication.TRANSACTION
            if res_pdu is not None and isinstance(res_pdu, NakPdu):
                print("meta")
                metadata_params = MetadataParams(
                    closure_requested=False,
                    file_size=self.file_data_len,
                    source_file_name=self.file_name,
                    dest_file_name=self.file_name,
                    checksum_type=ChecksumType.CRC_32,
                )
                req_pdu = MetadataPdu(pdu_conf=self.PDU_CONF, params=metadata_params)
            else:
                data = None
                if self.offset < self.file_data_len - self.buffer_size:
                    end = self.offset + self.buffer_size
                    data = self.file_data[self.offset : end]
                    print(f"file data {self.offset}-{end} of {self.file_data_len}")
                elif self.offset < self.file_data_len:
                    data = self.file_data[self.offset :]
                    print(
                        f"file data {self.offset}-{self.file_data_len} of {self.file_data_len} "
                        "aka final"
                    )
                else:
                    checksum = zlib.crc32(self.file_data).to_bytes(4, "little")
                    req_pdu = EofPdu(
                        self.PDU_CONF, file_checksum=checksum, file_size=len(self.file_data)
                    )
                    self.last_indication = Indication.EOF_SENT

                if data is not None:
                    fd_params = FileDataParams(
                        file_data=data, offset=self.offset, segment_metadata=None
                    )
                    req_pdu = FileDataPdu(pdu_conf=self.PDU_CONF, params=fd_params)

                    if self.offset + self.buffer_size <= self.file_data_len:
                        self.offset += self.buffer_size
                    else:
                        self.offset = self.file_data_len
        elif self.last_indication == Indication.EOF_SENT:
            if isinstance(res_pdu, AckPdu):
                self.got_eof_ack = True
                print("recv ack")
            elif isinstance(res_pdu, FinishedPdu):
                if self.got_eof_ack:
                    print("sent finish ack")
                    req_pdu = AckPdu(
                        directive_code_of_acked_pdu=DirectiveType.FINISHED_PDU,
                        condition_code_of_acked_pdu=ConditionCode.NO_ERROR,
                        transaction_status=TransactionStatus.TERMINATED,
                        pdu_conf=self.PDU_CONF,
                    )
                    self.last_indication = Indication.TRANSACTION_FINISHED
                else:
                    print("no ack")
                    self.last_indication = Indication.EOF_SENT
            else:
                # handle case with sender is done, but receiver is not
                print("eof sent")
                self.last_indication = Indication.TRANSACTION

        print(self.last_indication.name)

        return req_pdu


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
        "-s", "--buffer-size", type=int, default=950, help="file data buffer size"
    )
    args = parser.parse_args()

    file_name = args.file_path.split("/")[-1]
    try:
        OreSatFile(file_name)  # pylint: disable=E0602
    except ValueError:
        print("file name must be in card-name_key_unix-time.extension format")
        print("example: c3_test_123.txt")
        sys.exit(1)

    if args.random_data <= 0:
        if not os.path.isfile(args.file_path):
            print(f"file {args.file_path} not found")
            sys.exit(1)
        with open(args.file_path, "rb") as f:
            file_data = f.read()
    else:
        file_data = bytes([random.randint(0, 255) for _ in range(args.random_data)])

    event = Event()
    uplink_address = (args.host, args.uplink_port)
    downlink_address = (args.host, args.downlink_port)

    t = Thread(target=recv_thread, args=(downlink_address, args.bad_connection, event))
    t.start()

    entity = GroundEntity(args.file_path, file_data, args.buffer_size)

    edl_uplink_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    loop_num = 0
    seq_num = 1
    delay = args.loop_delay / 1000
    try:
        while not event.is_set():
            loop_num += 1

            if entity.last_indication == Indication.TRANSACTION_FINISHED:
                event.set()
                continue

            req_pdu = entity.loop()

            if req_pdu is not None:
                seq_num += 1

            if args.bad_connection and loop_num % random.randint(1, 5):
                continue  # simulate dropped packets

            if req_pdu is not None:
                packet = EdlPacket(req_pdu, seq_num, SRC_DEST_ORESAT)
                req_message = packet.pack(HMAC_KEY)
                edl_uplink_socket.sendto(req_message, uplink_address)
            sleep(delay)
    except KeyboardInterrupt:
        pass

    t.join()


if __name__ == "__main__":
    main()
