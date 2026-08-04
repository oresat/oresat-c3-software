import threading
import time
import unittest
from abc import ABCMeta
from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory

from cfdppy.handler import dest, source
from cfdppy.mib import (
    RemoteEntityConfig,
    RemoteEntityConfigTable,
)
from cfdppy.request import PutRequest
from cfdppy.restricted_filestore import RestrictedFilestore
from spacepackets.cfdp import CfdpLv
from spacepackets.cfdp.defs import ChecksumType, TransmissionMode
from spacepackets.cfdp.pdu import (
    AckPdu,
    EofPdu,
    FileDataPdu,
    FinishedPdu,
    MetadataPdu,
    NakPdu,  # noqa: F401
    PduFactory,
)
from spacepackets.cfdp.tlv import (
    DirectoryListingRequest,
    DirectoryParams,
    ProxyPutRequest,
    ProxyPutRequestParams,
    ProxyTransmissionMode,
)
from spacepackets.util import ByteFieldU8

from oresat_c3.protocols.cachestore import CacheStore
from oresat_c3.protocols.cfdp import DestEntityHandler, SourceEntityHandler


def put_request(destination: ByteFieldU8, file_path: str) -> PutRequest:
    """Creates a simple PutRequest for the file in file_path"""
    return PutRequest(
        destination_id=destination,
        source_file=Path(file_path),
        dest_file=Path(file_path),
        trans_mode=None,
        closure_requested=True,
    )


class TestCfdp(unittest.TestCase):
    TIMEOUT_DUR = 0.6

    def setUp(self):
        self.sat_file = Path("c3_tmp_123")
        self.cachedir = TemporaryDirectory()
        self.cache = CacheStore(self.cachedir.name)
        self.cache.create_file(self.sat_file)
        self.cache.write_data(self.sat_file, b"This is some example data\x01\x02\x03")

        self.cachedir_gnd = TemporaryDirectory()
        self.gnd_file = Path("c3_tmp_1234")
        # A less restricted filestore than the oresat one, so that we don't have to break that more.
        self.cache_gnd = RestrictedFilestore(Path(self.cachedir_gnd.name))
        self.cache_gnd.create_file(self.gnd_file)
        self.cache_gnd.write_data(self.gnd_file, b"This is some example data\x01\x02\x03", None)

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
                    # FIXME this value should come from EdlPacket.
                    max_packet_len=950,
                    closure_requested=True,
                    crc_on_transmission=False,
                    positive_ack_timer_interval_seconds=self.TIMEOUT_DUR,
                    nak_timer_interval_seconds=self.TIMEOUT_DUR,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.MODULAR,
                ),
            ]
        )
        self.cfdp_source_handler = SourceEntityHandler(
            self._put_req_queue,
            self._cfdp_src_queue,
            self._cfdp_tm_queue,
            self.cache,
            remote_entities,
            self.gnd_id,
            self.sat_id,
            self.stop_signal,
        )
        self.cfdp_dest_handler = DestEntityHandler(
            self._put_req_queue,
            self._cfdp_dest_queue,
            self._cfdp_tm_queue,
            self.cache,
            remote_entities,
            self.sat_id,
            self.stop_signal,
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
                    max_packet_len=950,
                    closure_requested=True,
                    crc_on_transmission=False,
                    positive_ack_timer_interval_seconds=self.TIMEOUT_DUR,
                    nak_timer_interval_seconds=self.TIMEOUT_DUR,
                    default_transmission_mode=TransmissionMode.ACKNOWLEDGED,
                    crc_type=ChecksumType.MODULAR,
                ),
            ]
        )
        self.cfdp_source_handler_gnd = SourceEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_src_queue_gnd,
            self._cfdp_tm_queue_gnd,
            self.cache_gnd,
            remote_entities_gnd,
            self.sat_id,
            self.gnd_id,
            self.stop_signal,
        )
        self.cfdp_dest_handler_gnd = DestEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_dest_queue_gnd,
            self._cfdp_tm_queue_gnd,
            self.cache_gnd,
            remote_entities_gnd,
            self.gnd_id,
            self.stop_signal,
        )

        self.cfdp_source_handler.start()
        self.cfdp_dest_handler.start()
        self.cfdp_source_handler_gnd.start()
        self.cfdp_dest_handler_gnd.start()

    def tearDown(self):
        self.cachedir.cleanup()
        self.cachedir_gnd.cleanup()
        self.stop_signal.set()
        self.cfdp_source_handler.join()
        self.cfdp_dest_handler.join()
        self.cfdp_source_handler_gnd.join()
        self.cfdp_dest_handler_gnd.join()

    def test_simple_transfer(self):
        """A basic transfer that ensures the no-loss path is working"""
        # The simple standard file transfer
        # src --> dst Metadata
        # src --> dst FileData
        # src --> dst EoF
        # src <-- dst Ack (EoF)
        # src <-- dst Finished
        # src --> dst Ack (Finished)

        put = put_request(self.sat_id, self.gnd_file.name)
        self._put_req_queue_gnd.put(put)
        time.sleep(0.2)

        # src --> Metadata
        self._src_gnd_to_sc_dest(0.15, MetadataPdu)
        # src --> Filedata
        self._src_gnd_to_sc_dest(0.15, FileDataPdu)
        # src --> EoF
        self._src_gnd_to_sc_dest(0.15, EofPdu)
        # dst <-- Ack (EoF)
        self._dest_sc_to_gnd_src(0.15, AckPdu)
        # dst <-- Finished
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)
        # src --> Ack (Finished)
        self._src_gnd_to_sc_dest(0.15, AckPdu)

        # Make sure we've returned to idle / empty.
        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step, source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(self.gnd_file), self.cache_gnd.read_data(self.gnd_file, None)
        )
        self.cache.delete_file(self.gnd_file)

    def test_dropped_ack(self):
        """What happens if the first ack gets dropped?"""
        # src --> Metadata
        # src --> FileData
        # src --> EoF
        # dst  X  Ack (EoF)
        # dst --> Finished
        # ??? According to 4.7.1 b) the origional PDU should be re-issued. So:
        # src --> EoF
        # dst --> Finished # same timeout as the EOF, not acked so re-issued as well.
        # dst --> Ack (EoF)
        # dst --> Finished
        # src --> Ack (Finished)

        put = put_request(self.sat_id, self.gnd_file.name)
        self._put_req_queue_gnd.put(put)
        time.sleep(0.2)

        # src --> Metadata
        self._src_gnd_to_sc_dest(0.15, MetadataPdu)
        # src --> Filedata
        self._src_gnd_to_sc_dest(0.15, FileDataPdu)
        # src --> EoF
        self._src_gnd_to_sc_dest(0.15, EofPdu)
        # dst X-- Ack (EoF)
        time.sleep(0.15)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self._cfdp_tm_queue.get()  # drop the pdu
        # dst <-- Finished
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)
        # A timeout will occur here.
        # src --> EoF
        self._src_gnd_to_sc_dest(0.15, EofPdu)
        # dst <-- Ack (EoF)
        self._dest_sc_to_gnd_src(0.15, AckPdu)
        # dst <-- Finished
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)
        # src --> Ack (Finished)
        self._src_gnd_to_sc_dest(0.15, AckPdu)

        # Make sure we've returned to idle / empty.
        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step, source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(self.gnd_file), self.cache_gnd.read_data(self.gnd_file, None)
        )
        self.cache.delete_file(self.gnd_file)

    def test_proxy_put_operation(self):
        """
        The ground asks the spacecraft to send a file to someone (the ground in our case), the
        spacecraft creates a new transaction to send it, then starts a transaction to send a
        "we've finished" message.
        """
        # gnd_src --> s/c_dst Metadata      T1
        # gnd_src --> s/c_dst Eof           T1
        # gnd_src <-- s/c_dst Ack (EoF)     T1
        # gnd_src <-- s/c_dst Finished      T1
        # gnd_src --> s/c_dst Ack (Fin)     T1

        # gnd_dst <-- s/c_src Metadata      T2
        # gnd_dst <-- s/c_src Filedata      T2
        # gnd_dst <-- s/c_src Eof           T2
        # gnd_dst --> s/c_src Ack (EoF)     T2
        # gnd_dst --> s/c_src Finished      T2
        # gnd_dst <-- s/c_src Ack (Fin)     T2

        # gnd_src <-- s/c_dst Metadata      T3
        # gnd_src <-- s/c_dst Eof           T3
        # gnd_src --> s/c_dst Ack (EoF)     T3
        # gnd_src --> s/c_dst Finished      T3
        # gnd_src <-- s/c_dst Ack (Fin)     T3
        proxy_put = ProxyPutRequest(
            ProxyPutRequestParams(
                dest_entity_id=self.gnd_id,
                source_file_name=CfdpLv.from_str(self.sat_file.name),
                dest_file_name=CfdpLv.from_str(self.sat_file.name),
            )
        ).to_generic_msg_to_user_tlv()
        # Yamcs will always send a proxy transmission mode message, for both class 1 or class 2.
        proxy_trans = ProxyTransmissionMode(
            TransmissionMode.ACKNOWLEDGED
        ).to_generic_msg_to_user_tlv()
        put = PutRequest(
            destination_id=self.sat_id,
            source_file=None,
            dest_file=None,
            trans_mode=None,
            closure_requested=True,
            msgs_to_user=[proxy_put, proxy_trans],
        )

        self._put_req_queue_gnd.put(put)
        time.sleep(0.2)

        # gnd_src --> s/c_dst Metadata      T1
        self._src_gnd_to_sc_dest(0.15, MetadataPdu)
        # gnd_src --> s/c_dst Eof           T1
        self._src_gnd_to_sc_dest(0.15, EofPdu)
        # gnd_src <-- s/c_dst Ack (EoF)     T1
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self._dest_sc_to_gnd_src(0.15, AckPdu)
        # gnd_src <-- s/c_dst Finished      T1
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)
        # gnd_src --> s/c_dst Ack (Fin)     T1
        self._src_gnd_to_sc_dest(0.15, AckPdu)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())

        # gnd_dst <-- s/c_src Metadata      T2
        self._src_sc_to_gnd_dest(0.15, MetadataPdu)
        # gnd_dst <-- s/c_src Filedata      T2
        self._src_sc_to_gnd_dest(0.15, FileDataPdu)
        # gnd_dst <-- s/c_src Eof           T2
        self._src_sc_to_gnd_dest(0.15, EofPdu)
        # gnd_dst --> s/c_src Ack (EoF)     T2
        self._dest_gnd_to_sc_src(0.15, AckPdu)
        # gnd_dst --> s/c_src Finished      T2
        self._dest_gnd_to_sc_src(0.15, FinishedPdu)
        # gnd_dst <-- s/c_src Ack (Fin)     T2
        self._src_sc_to_gnd_dest(0.15, AckPdu)

        # gnd_dst <-- s/c_src Metadata      T3
        self._src_sc_to_gnd_dest(0.15, MetadataPdu)
        # gnd_dst <-- s/c_src Eof           T3
        self._src_sc_to_gnd_dest(0.15, EofPdu)
        # gnd_dst --> s/c_src Ack (EoF)     T3
        self._dest_gnd_to_sc_src(0.15, AckPdu)
        # gnd_dst --> s/c_src Finished      T3
        self._dest_gnd_to_sc_src(0.15, FinishedPdu)
        # gnd_dst <-- s/c_src Ack (Fin)     T3
        self._src_sc_to_gnd_dest(0.15, AckPdu)

        # Make sure we've returned to idle / empty.
        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step, source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(self.sat_file), self.cache_gnd.read_data(self.sat_file, None)
        )
        self.cache_gnd.delete_file(self.sat_file)

    def test_directory_listing(self):
        """
        The ground asks the spacecraft for the vfs root directory listing to be sent back
        as a file. The spacecraft sends the directory listing as a file. The ground requests
        that the spacecraft send a proxy put response (T3).

        This will attempt to mimic the YAMCS request since it breaks the upstream spacepackets.py
        package.
        """
        # gnd_src --> s/c_dst Metadata      T1
        # gnd_src --> s/c_dst Eof           T1
        # gnd_src <-- s/c_dst Ack (EoF)     T1
        # gnd_src <-- s/c_dst Finished      T1
        # gnd_src --> s/c_dst Ack (Fin)     T1

        # gnd_dst <-- s/c_src Metadata      T2
        # gnd_dst <-- s/c_src Filedata      T2
        # gnd_dst <-- s/c_src Eof           T2
        # gnd_dst --> s/c_src Ack (EoF)     T2
        # gnd_dst --> s/c_src Finished      T2
        # gnd_dst <-- s/c_src Ack (Fin)     T2

        # gnd_src <-- s/c_dst Metadata      T3
        # gnd_src <-- s/c_dst Eof           T3
        # gnd_src --> s/c_dst Ack (EoF)     T3
        # gnd_src --> s/c_dst Finished      T3
        # gnd_src <-- s/c_dst Ack (Fin)     T3

        # this is put into the working directory. This is awful and should be fixed, but that would
        # require breaking cachestore even more.
        dir_listing_gnd = ".dirlist.notsaved"
        dir_listing_sc = "c3_dirlist_0"
        dir_req = DirectoryListingRequest(
            DirectoryParams(
                dir_path=CfdpLv.from_str(""), dir_file_name=CfdpLv.from_str(dir_listing_gnd)
            )
        ).to_generic_msg_to_user_tlv()
        put = PutRequest(
            destination_id=self.sat_id,
            source_file=None,
            dest_file=None,
            trans_mode=None,
            closure_requested=True,
            msgs_to_user=[dir_req],
        )
        self._put_req_queue_gnd.put(put)
        time.sleep(0.2)

        # gnd_src --> s/c_dst Metadata      T1
        self._src_gnd_to_sc_dest(0.15, MetadataPdu)
        # gnd_src --> s/c_dst Eof           T1
        self._src_gnd_to_sc_dest(0.15, EofPdu)
        # gnd_src <-- s/c_dst Ack (EoF)     T1
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self._dest_sc_to_gnd_src(0.15, AckPdu)
        # gnd_src <-- s/c_dst Finished      T1
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)
        # gnd_src --> s/c_dst Ack (Fin)     T1
        self._src_gnd_to_sc_dest(0.15, AckPdu)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())

        # gnd_dst <-- s/c_src Metadata      T2
        self._src_sc_to_gnd_dest(0.15, MetadataPdu)
        # gnd_dst <-- s/c_src Filedata      T2
        self._src_sc_to_gnd_dest(0.15, FileDataPdu)
        # gnd_dst <-- s/c_src Eof           T2
        self._src_sc_to_gnd_dest(0.15, EofPdu)
        # gnd_dst --> s/c_src Ack (EoF)     T2
        self._dest_gnd_to_sc_src(0.15, AckPdu)
        # gnd_dst --> s/c_src Finished      T2
        self._dest_gnd_to_sc_src(0.15, FinishedPdu)
        # gnd_dst <-- s/c_src Ack (Fin)     T2
        self._src_sc_to_gnd_dest(0.15, AckPdu)

        # gnd_dst <-- s/c_src Metadata      T3
        self._src_sc_to_gnd_dest(0.15, MetadataPdu)
        # gnd_dst <-- s/c_src Eof           T3
        self._src_sc_to_gnd_dest(0.15, EofPdu)
        # gnd_dst --> s/c_src Ack (EoF)     T3
        self._dest_gnd_to_sc_src(0.15, AckPdu)
        # gnd_dst --> s/c_src Finished      T3
        self._dest_gnd_to_sc_src(0.15, FinishedPdu)
        # gnd_dst <-- s/c_src Ack (Fin)     T3
        self._src_sc_to_gnd_dest(0.15, AckPdu)

        # Make sure we've returned to idle / empty.
        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step, source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(Path(dir_listing_sc)),
            self.cache_gnd.read_data(Path(dir_listing_gnd), None),
        )
        self.cache.delete_file(Path(dir_listing_sc))
        self.cache_gnd.delete_file(Path(dir_listing_gnd))

    def test_timed_out(self):
        """
        After the first 3 PDUs, stop transfering pdus. This lets us test both the source and the
        dest timing out.
        """
        # src --> Metadata
        # src --> FileData
        # src --> EoF
        # timeout
        # src --> EoF
        # timeout
        # src --> EoF
        # timeout
        # Transaction Ended
        put = put_request(self.sat_id, self.gnd_file.name)
        self._put_req_queue_gnd.put(put)
        time.sleep(0.2)

        # src --> Metadata
        self._src_gnd_to_sc_dest(0.15, MetadataPdu)
        # src --> Filedata
        self._src_gnd_to_sc_dest(0.15, FileDataPdu)
        # src --> EoF
        self._src_gnd_to_sc_dest(0.15, EofPdu)

        self._cfdp_tm_queue.get()  # drop the ack(eof)
        self._cfdp_tm_queue.get()  # drop the fin
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step,
            source.TransactionStep.WAITING_FOR_EOF_ACK,
        )
        self.assertEqual(
            self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.WAITING_FOR_FINISHED_ACK
        )
        time.sleep(self.TIMEOUT_DUR + 0.02)

        pdu = self._cfdp_tm_queue_gnd.get()
        self.assertIsInstance(pdu.pdu, EofPdu)
        pdu = self._cfdp_tm_queue.get()
        self.assertIsInstance(pdu.pdu, FinishedPdu)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        time.sleep(self.TIMEOUT_DUR + 0.02)

        pdu = self._cfdp_tm_queue_gnd.get()
        self.assertIsInstance(pdu.pdu, EofPdu)
        pdu = self._cfdp_tm_queue.get()
        self.assertIsInstance(pdu.pdu, FinishedPdu)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.WAITING_FOR_FINISHED_ACK
        )
        time.sleep(self.TIMEOUT_DUR + 0.02)

        # think it should crash here.
        pdu = self._cfdp_tm_queue_gnd.get()
        self.assertIsInstance(pdu.pdu, EofPdu)
        pdu = self._cfdp_tm_queue.get()
        self.assertIsInstance(pdu.pdu, FinishedPdu)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        time.sleep(self.TIMEOUT_DUR + 0.02)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        time.sleep(self.TIMEOUT_DUR * 2 + 0.02)

        # Make sure we've returned to idle / empty.
        time.sleep(1)
        self.assertTrue(self._cfdp_tm_queue_gnd.empty())
        self.assertEqual(self.cfdp_dest_handler.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(self.cfdp_source_handler.source_handler.step, source.TransactionStep.IDLE)
        self.assertTrue(self._cfdp_tm_queue.empty())
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step, source.TransactionStep.IDLE
        )

    def _src_gnd_to_sc_dest(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue_gnd.get().pack())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_dest_queue.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _dest_gnd_to_sc_src(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue_gnd.get().pack())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_src_queue.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _src_sc_to_gnd_dest(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue.get().pack())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_dest_queue_gnd.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _dest_sc_to_gnd_src(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue.get().pack())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_src_queue_gnd.put(pdu)
        if delay > 0:
            time.sleep(delay)
