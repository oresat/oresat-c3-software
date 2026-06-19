import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from queue import Empty, SimpleQueue
from tempfile import NamedTemporaryFile
from typing import Any

from cfdppy import get_packet_destination
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
from spacepackets.cfdp.pdu import AckPdu, EofPdu, FileDataPdu, FinishedPdu, MetadataPdu, PduFactory
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


def put_request(destination: ByteFieldU8, file_path: str) -> PutRequest:
    """Creates a simple PutRequest for the file in file_path"""
    return PutRequest(
        destination_id=destination,
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
        self.stop_signal = threading.Event()

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
            self.sat_id,
            self.stop_signal
        )
        self.cfdp_dest_handler = DestEntityHandler(
            self._put_req_queue,
            self._cfdp_dest_queue,
            self._cfdp_tm_queue,
            remote_entities,
            self.sat_id,
            self.stop_signal
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
            self.gnd_id,
            self.stop_signal
        )
        self.cfdp_dest_handler_gnd = DestEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_dest_queue_gnd,
            self._cfdp_tm_queue_gnd,
            remote_entities_gnd,
            self.gnd_id,
            self.stop_signal
        )

        self.cfdp_source_handler.start()
        self.cfdp_dest_handler.start()
        self.cfdp_source_handler_gnd.start()
        self.cfdp_dest_handler_gnd.start()

    def tearDown(self):
        self.cfdp_source_handler.join()
        self.cfdp_dest_handler.join()
        self.cfdp_source_handler_gnd.join()
        self.cfdp_dest_handler_gnd.join()
        self.stop_signal.set()
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
        # pdus = [MetadataPdu, FileDataPdu, EofPdu, AckPdu, FinishedPdu, AckPdu]

        put = put_request(self.sat_id, self.file.name)

        self._put_req_queue_gnd.put(put)

        time.sleep(0.2)
        pdu_packed = self._cfdp_tm_queue_gnd.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, MetadataPdu)
        self._cfdp_dest_queue.put(pdu.pdu)

        time.sleep(0.15)
        pdu_packed = self._cfdp_tm_queue_gnd.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, FileDataPdu)
        self._cfdp_dest_queue.put(pdu.pdu)

        time.sleep(0.15)
        pdu_packed = self._cfdp_tm_queue_gnd.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        print(get_packet_destination(pdu.pdu))
        self.assertIsInstance(pdu.pdu, EofPdu)
        self._cfdp_dest_queue.put(pdu.pdu)

        time.sleep(0.15)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        pdu_packed = self._cfdp_tm_queue.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, AckPdu)
        self._cfdp_src_queue_gnd.put(pdu.pdu)

        time.sleep(0.15)
        pdu_packed = self._cfdp_tm_queue.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, FinishedPdu)
        self._cfdp_src_queue_gnd.put(pdu.pdu)

        time.sleep(0.15)
        self.assertTrue(self._cfdp_tm_queue.empty())
        pdu_packed = self._cfdp_tm_queue_gnd.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, AckPdu)
        self._cfdp_dest_queue.put(pdu.pdu)

        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step,
            source.TransactionStep.IDLE
        )


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
