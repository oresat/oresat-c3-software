import unittest
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
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

from oresat_c3.protocols.cfdp import DestEntityHandler, SourceEntityHandler


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

        self.gnd_id = ByteFieldU8(0)
        self.sat_id = ByteFieldU8(1)

        self._put_req_queue = SimpleQueue()
        self._cfdp_src_queue = SimpleQueue()
        self._cfdp_dest_queue = SimpleQueue()
        self._cfdp_tm_queue = SimpleQueue()

        # Satellite handling
        remote_entities = RemoteEntityConfigTable(
            [
                RemoteEntityConfig(
                    entity_id=self.gnd_id,
                    max_file_segment_len=None,
                    # FIXME this value should come from EdlPacket but EdlPacket does not define it.
                    # How does the exact value get determined? Currently it's just a mirror of the
                    # value in edl_file_upload.py
                    max_packet_len=950,
                    closure_requested=False,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.MODULAR,
                ),
            ]
        )
        self.cfdp_source_handler = SourceEntityHandler(
            self._put_req_queue,
            self._cfdp_src_queue,
            self._cfdp_tm_queue,
            remote_entities,
            self.gnd_id,
            self.sat_id
        )
        self.cfdp_dest_handler = DestEntityHandler(
            self._put_req_queue,
            self._cfdp_dest_queue,
            self._cfdp_tm_queue,
            remote_entities,
            self.sat_id
        )

        # Ground station handling


        self._put_req_queue_gnd = SimpleQueue()
        self._cfdp_src_queue_gnd = SimpleQueue()
        self._cfdp_dest_queue_gnd = SimpleQueue()
        self._cfdp_tm_queue_gnd = SimpleQueue()

        remote_entities_gnd = RemoteEntityConfigTable(
            [
                RemoteEntityConfig(
                    entity_id=self.sat_id,
                    max_file_segment_len=None,
                    # FIXME this value should come from EdlPacket but EdlPacket does not define it.
                    # How does the exact value get determined? Currently it's just a mirror of the
                    # value in edl_file_upload.py
                    max_packet_len=950,
                    closure_requested=False,
                    crc_on_transmission=False,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.MODULAR,
                ),
            ]
        )
        self.cfdp_source_handler_gnd = SourceEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_src_queue_gnd,
            self._cfdp_tm_queue_gnd,
            remote_entities_gnd,
            self.sat_id,
            self.gnd_id
        )
        self.cfdp_dest_handler_gnd = DestEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_dest_queue_gnd,
            self._cfdp_tm_queue_gnd,
            remote_entities_gnd,
            self.gnd_id
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

        self.cfdp_source_handler_gnd

    # @unittest.skip("FIXME: Revisit this after upgrading cfdppy to 0.6.0")
    # def test_missing_ack(self):
    #     """What happens if the first ack gets dropped?"""
    #     # src --> Metadata
    #     # src --> FileData
    #     # src --> EoF
    #     # dst  X  Ack (EoF)
    #     # dst <-- Finished
    #     # ??? According to 4.7.1 b) the origional PDU should be re-issued. So:
    #     # src --> EoF
    #     # dst <-- Ack (EoF)
    #     # dst <-- Finished
    #     # src --> Ack (Finished)
    #     pdus = [MetadataPdu, FileDataPdu, EofPdu, AckPdu, FinishedPdu, AckPdu]

    #     put = put_request(self.dst_id, self.file.name)
    #     self.assertTrue(self.src.put_request(put))

    #     for i, pdutype in enumerate(pdus):
    #         self.src.state_machine()
    #         self.dst.state_machine()

    #         print("SRC:", self.src.step, "| DST:", self.src.step)

    #         while self.src.packets_ready:
    #             pdu = self.src.get_next_packet().pdu
    #             print("\nSRC ", pdu, "\n")
    #             self.assertIsInstance(pdu, pdutype)
    #             self.dst.state_machine(pdu)

    #         while self.dst.packets_ready:
    #             pdu = self.dst.get_next_packet().pdu
    #             self.assertIsInstance(pdu, pdutype)
    #             if i == 3:  # Skip first Ack
    #                 break
    #             print("\nSRC ", pdu, "\n")
    #             with self.assertRaises(PduIgnoredForSource):
    #                 self.src.state_machine(pdu)

    #     self.src.state_machine()
    #     self.dst.state_machine()

    #     self.assertEqual(self.src.step, source.TransactionStep.IDLE)
    #     self.assertEqual(self.dst.step, dest.TransactionStep.IDLE)


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
