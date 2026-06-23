import threading
import time
import unittest
from abc import ABCMeta
from datetime import timedelta
from pathlib import Path
from queue import SimpleQueue
from tempfile import TemporaryDirectory

from cfdppy.handler import dest, source
from cfdppy.mib import (
    CheckTimerProvider,
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
    NakPdu,
    PduFactory,
)
from spacepackets.cfdp.tlv import (
    DirectoryListingRequest,
    DirectoryParams,
    ProxyPutRequest,
    ProxyPutRequestParams,
    ProxyTransmissionMode,
)
from spacepackets.countdown import Countdown
from spacepackets.util import ByteFieldU8

from oresat_c3.protocols.cachestore import CacheStore
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
        closure_requested=True,
    )


class TestCfdp(unittest.TestCase):
    def setUp(self):
        self.sat_file = Path("c3_tmp_123")
        self.cachedir = TemporaryDirectory()
        self.cache = CacheStore(self.cachedir.name)
        self.cache.create_file(self.sat_file)
        self.cache.write_data(self.sat_file, b"This is some example data\x01\x02\x03")

        self.cachedir_gnd = TemporaryDirectory()
        self.cache_gnd = RestrictedFilestore(Path(self.cachedir_gnd.name))
        self.gnd_file = Path("c3_tmp_1234")
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
            self.stop_signal
        )
        self.cfdp_dest_handler = DestEntityHandler(
            self._put_req_queue,
            self._cfdp_dest_queue,
            self._cfdp_tm_queue,
            self.cache,
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
                    max_packet_len=950,
                    closure_requested=True,
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
            self.cache_gnd,
            remote_entities_gnd,
            self.sat_id,
            self.gnd_id,
            self.stop_signal
        )
        self.cfdp_dest_handler_gnd = DestEntityHandler(
            self._put_req_queue_gnd,
            self._cfdp_dest_queue_gnd,
            self._cfdp_tm_queue_gnd,
            self.cache_gnd,
            remote_entities_gnd,
            self.gnd_id,
            self.stop_signal
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
        self.file.close()

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
        self.assertEqual(
            self.cfdp_source_handler.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(self.gnd_file),
            self.cache_gnd.read_data(self.gnd_file)
        )
        self.cache.delete_file(self.gnd_file)

    # Broken for now. For some reason CFDP stops resending EOFs after recieving a finished PDU,
    # leaving it stuck waiting for an ACK (EOF) without resending EOFs.
    # @unittest.skip("FIXME: stops resending EoFs after recieving finished")
    def test_dropped_ack(self):
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

        put = put_request(self.sat_id, self.file.name)
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
        pdu_packed = self._cfdp_tm_queue.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        # dst <-- Finished
        self._dest_sc_to_gnd_src(0.15, FinishedPdu)

        print(self.cfdp_source_handler_gnd.source_handler.step)

        # dst <-- Finished
        time.sleep(0.15)
        pdu_packed = self._cfdp_tm_queue.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, FinishedPdu)
        self._cfdp_src_queue_gnd.put(pdu.pdu)
        time.sleep(1)

        print(self.cfdp_source_handler_gnd.source_handler.step)

        time.sleep(100)

        # src --> Ack (Finished)
        time.sleep(0.15)
        self.assertTrue(self._cfdp_tm_queue.empty())
        pdu_packed = self._cfdp_tm_queue.get()
        pdu = PduFactory.from_raw_to_holder(pdu_packed)
        self.assertIsInstance(pdu.pdu, AckPdu)
        self._cfdp_dest_queue.put(pdu.pdu)

        # Make sure we've returned to idle / empty.
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
        self.assertEqual(
            self.cache.read_data(self.gnd_file),
            self.cache_gnd.read_data(self.gnd_file)
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
                dest_file_name=CfdpLv.from_str(self.sat_file.name)
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
        self.assertEqual(
            self.cfdp_source_handler.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(self.sat_file),
            self.cache_gnd.read_data(self.sat_file)
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
        dir_req = DirectoryListingRequest(
            DirectoryParams(
                dir_path=CfdpLv.from_str(""),
                dir_file_name=CfdpLv.from_str(dir_listing_gnd)
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
        self.assertEqual(
            self.cfdp_source_handler.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(self.cfdp_dest_handler_gnd.dest_handler.step, dest.TransactionStep.IDLE)
        self.assertEqual(
            self.cfdp_source_handler_gnd.source_handler.step,
            source.TransactionStep.IDLE
        )
        self.assertEqual(
            self.cache.read_data(Path(dir_listing_gnd)),
            self.cache_gnd.read_data(Path(dir_listing_gnd), None)
        )
        self.cache.delete_file(Path(dir_listing_gnd))
        self.cache_gnd.delete_file(Path(dir_listing_gnd))


    def _src_gnd_to_sc_dest(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue_gnd.get())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_dest_queue.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _dest_gnd_to_sc_src(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue_gnd.get())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_src_queue.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _src_sc_to_gnd_dest(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue.get())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_dest_queue_gnd.put(pdu)
        if delay > 0:
            time.sleep(delay)

    def _dest_sc_to_gnd_src(self, delay: float, expected_type: ABCMeta) -> None:
        pdu = PduFactory.from_raw(self._cfdp_tm_queue.get())
        self.assertIsInstance(pdu, expected_type)
        self._cfdp_src_queue_gnd.put(pdu)
        if delay > 0:
            time.sleep(delay)
