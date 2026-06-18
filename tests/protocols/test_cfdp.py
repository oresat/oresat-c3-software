import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from cfdppy.exceptions import PduIgnoredForSource
from cfdppy.handler import dest, source
from cfdppy.handler.dest import DestHandler
from cfdppy.handler.source import SourceHandler
from cfdppy.mib import (
    CheckTimerProvider,
    DefaultFaultHandlerBase,
    IndicationConfig,
    LocalEntityConfig,
    RemoteEntityConfig,
    RemoteEntityConfigTable,
)
from cfdppy.request import PutRequest
from cfdppy.user import (
    CfdpUserBase,
    FileSegmentRecvdParams,
    MetadataRecvParams,
    TransactionFinishedParams,
    TransactionParams,
)
from spacepackets.cfdp.defs import ChecksumType, ConditionCode, TransactionId, TransmissionMode
from spacepackets.cfdp.pdu import AckPdu, EofPdu, FileDataPdu, FinishedPdu, MetadataPdu
from spacepackets.countdown import Countdown
from spacepackets.seqcount import SeqCountProvider
from spacepackets.util import ByteFieldU8


class CountdownProvider(CheckTimerProvider):
    """Copied from the cfdppy example.

    I think this is to allow for custom timeouts based on latency between local and remote
    entities? It doesn't set all the timers though, ACK timer I'm looking at you.
    """

    def provide_check_timer(self, local_entity_id, remote_entity_id, entity_type) -> Countdown:
        return Countdown(timedelta(seconds=5.0))


class PrintFaults(DefaultFaultHandlerBase):
    """Prints all faults to stdout"""

    def notice_of_suspension_cb(self, transaction_id, cond, progress):
        # print(f"Transaction {transaction_id} suspended: {cond}. Progress {progress}")
        pass

    def notice_of_cancellation_cb(self, transaction_id, cond, progress):
        # print(f"Transaction {transaction_id} cancelled: {cond}. Progress {progress}")
        pass

    def abandoned_cb(self, transaction_id, cond, progress):
        # print(f"Transaction {transaction_id} abandoned: {cond}. Progress {progress}")
        pass

    def ignore_cb(self, transaction_id, cond, progress):
        # print(f"Transaction {transaction_id} ignored: {cond}. Progress {progress}")
        pass


class PrintUser(CfdpUserBase):
    """Prints all indications to sdtout"""

    def transaction_indication(self, transaction_indication_params: TransactionParams):
        # print(f"Indication: Transaction. {transaction_indication_params}")
        pass

    def eof_sent_indication(self, transaction_id: TransactionId):
        # print(f"Indication: EOF Sent for {transaction_id}.")
        pass

    def transaction_finished_indication(self, params: TransactionFinishedParams):
        # print(f"Indication: Transaction Finished. {params}")
        pass

    def metadata_recv_indication(self, params: MetadataRecvParams):
        # print(f"Indication: Metadata Recv. {params}")
        pass

    def file_segment_recv_indication(self, params: FileSegmentRecvdParams):
        # print(f"Indication: File Segment Recv. {params}")
        pass

    def report_indication(self, transaction_id: TransactionId, status_report: Any):
        # print("Indication: Report for {transaction_id}. {status_report}")
        pass

    def suspended_indication(self, transaction_id: TransactionId, cond_code: ConditionCode):
        # print("Indication: Suspended for {transaction_id}. {cond_code}")
        pass

    def resumed_indication(self, transaction_id: TransactionId, progress: int):
        # print("Indication: Resumed for {transaction_id}. {progress}")
        pass

    def fault_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        # print("Indication: Fault for {transaction_id}. {cond_code}. {progress}")
        pass

    def abandoned_indication(
        self, transaction_id: TransactionId, cond_code: ConditionCode, progress: int
    ):
        # print("Indication: Abandoned for {transaction_id}. {cond_code}. {progress}")
        pass

    def eof_recv_indication(self, transaction_id: TransactionId):
        # print("Indication: EOF Recv for {transaction_id}")
        pass


def put_request(dest: ByteFieldU8, file_path: str) -> PutRequest:
    """Creates a simple PutRequest for the file in file_path"""
    return PutRequest(
        destination_id=dest,
        source_file=Path(file_path),
        dest_file=Path(file_path),
        trans_mode=None,
        closure_requested=None,
    )


# @unittest.skip("FIXME: Revisit this after upgrading cfdppy to 0.6.0")
class TestCfdp(unittest.TestCase):
    def setUp(self):
        self.file = NamedTemporaryFile()
        self.file.write(b"This is some example data\x01\x02\x03")
        self.file.flush()

        self.src_id = ByteFieldU8(0)
        self.dst_id = ByteFieldU8(1)

        src_cfg = LocalEntityConfig(
            local_entity_id=self.src_id,
            indication_cfg=IndicationConfig(),
            default_fault_handlers=PrintFaults(),
        )

        dst_cfg = LocalEntityConfig(
            local_entity_id=self.dst_id,
            indication_cfg=IndicationConfig(),
            default_fault_handlers=PrintFaults(),
        )

        src_remote_entities = RemoteEntityConfigTable(
            [
                RemoteEntityConfig(
                    entity_id=self.dst_id,
                    max_file_segment_len=None,
                    max_packet_len=950,
                    closure_requested=False,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.CRC_32,
                ),
            ]
        )

        dst_remote_entities = RemoteEntityConfigTable(
            [
                RemoteEntityConfig(
                    entity_id=self.src_id,
                    max_file_segment_len=None,
                    max_packet_len=950,
                    closure_requested=False,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.CRC_32,
                ),
            ]
        )

        self.src = SourceHandler(
            cfg=src_cfg,
            user=PrintUser(),
            remote_cfg_table=src_remote_entities,
            check_timer_provider=CountdownProvider(),
            seq_num_provider=SeqCountProvider(16),
        )

        self.dst = DestHandler(
            cfg=dst_cfg,
            user=PrintUser(),
            remote_cfg_table=dst_remote_entities,
            check_timer_provider=CountdownProvider(),
        )

    def tearDown(self):
        self.file.close()

    def test_simple_transfer(self):
        """A basic transfer that ensures the no-loss path is working"""
        # The simple standard file transfer
        # src --> Metadata
        # src --> FileData
        # src --> EoF
        # dst <-- Ack (EoF)
        # dst <-- Finished
        # src --> Ack (Finished)
        pdus = [MetadataPdu, FileDataPdu, EofPdu, AckPdu, FinishedPdu, AckPdu]

        put = put_request(self.dst_id, self.file.name)
        self.assertTrue(self.src.put_request(put))

        for pdutype in pdus:
            self.src.state_machine()
            self.dst.state_machine()

            while self.src.packets_ready:
                pdu = self.src.get_next_packet().pdu
                self.assertIsInstance(pdu, pdutype)
                self.dst.state_machine(pdu)

            while self.dst.packets_ready:
                pdu = self.dst.get_next_packet().pdu
                self.assertIsInstance(pdu, pdutype)
                self.src.state_machien(pdu)

        self.src.state_machine()
        self.dst.state_machine()

        self.assertEqual(self.src.step, source.TransactionStep.IDLE)
        self.assertEqual(self.dst.step, dest.TransactionStep.IDLE)

    @unittest.skip("FIXME: Revisit this after upgrading cfdppy to 0.6.0")
    def test_missing_ack(self):
        """What happens if the first ack gets dropped?"""
        # src --> Metadata
        # src --> FileData
        # src --> EoF
        # dst  X  Ack (EoF)
        # dst <-- Finished
        # ??? According to 4.7.1 b) the origional PDU should be re-issued. So:
        # src --> EoF
        # dst <-- Ack (EoF)
        # dst <-- Finished
        # src --> Ack (Finished)
        pdus = [MetadataPdu, FileDataPdu, EofPdu, AckPdu, FinishedPdu, AckPdu]

        put = put_request(self.dst_id, self.file.name)
        self.assertTrue(self.src.put_request(put))

        for i, pdutype in enumerate(pdus):
            self.src.state_machine()
            self.dst.state_machine()

            print("SRC:", self.src.step, "| DST:", self.src.step)

            while self.src.packets_ready:
                pdu = self.src.get_next_packet().pdu
                print("\nSRC ", pdu, "\n")
                self.assertIsInstance(pdu, pdutype)
                self.dst.state_machine(pdu)

            while self.dst.packets_ready:
                pdu = self.dst.get_next_packet().pdu
                self.assertIsInstance(pdu, pdutype)
                if i == 3:  # Skip first Ack
                    break
                print("\nSRC ", pdu, "\n")
                with self.assertRaises(PduIgnoredForSource):
                    self.src.state_machine(pdu)

        self.src.state_machine()
        self.dst.state_machine()

        self.assertEqual(self.src.step, source.TransactionStep.IDLE)
        self.assertEqual(self.dst.step, dest.TransactionStep.IDLE)


#
#
#
#    def run(self):
#        while packet := self.downlink.get():
#            with self.lock:
#                self.src.state_machine(packet)
#                self.src.state_machine()
#                while self.src.packets_ready:
#                    pdu = self.src.get_next_packet().pdu
#                    self.uplink.put(pdu)
#
