"""Unit tests for EdlPacket."""

import unittest
from enum import IntEnum

from spacepackets.uslp.defs import UslpChecksumError, UslpInvalidRawPacketOrFrameLenError
from spacepackets.uslp.frame import FrameType

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandResponse
from oresat_c3.protocols.edl_packet import (
    SRC_DEST_ORESAT,
    SRC_DEST_UNICLOGS,
    EdlPacket,
)
from oresat_c3.protocols.sdls import SdlsInvalidHmacError, verify_sdls
from oresat_c3.protocols.uslp import TC_MIN_LEN, make_frame, unpack_frame


class TestEdlPacket(unittest.TestCase):
    """Test the EdlPacket."""

    def setUp(self):
        self.hmac_key = b"\x00" * 128
        self.seq_num = 0

    def test_basic_pack_unpack(self):
        """Test packing and unpacking an EDL request packet and response packet."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        edl_message_req = edl_packet_req.pack()
        edl_packet_req2 = EdlPacket.from_payload(edl_message_req, 0, SRC_DEST_ORESAT)
        self.assertEqual(edl_packet_req, edl_packet_req2)

        payload = EdlCommandResponse(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_res = EdlPacket(payload, self.seq_num, SRC_DEST_UNICLOGS)
        edl_message_res = edl_packet_res.pack()
        edl_packet_res2 = EdlPacket.from_payload(edl_message_res, 0, SRC_DEST_UNICLOGS)
        self.assertEqual(edl_packet_res, edl_packet_res2)

    def test_unpack_short_packet(self):
        """Test unpacking an message that is to short to be a valid EDL packet."""

        # Preparing a packet that is shorter than the minimum length
        short_packet = b"\x00" * (TC_MIN_LEN - 1)

        # Test if EdlPacketError "Packet too short" exception is thrown
        with self.assertRaises(UslpInvalidRawPacketOrFrameLenError):
            frame = unpack_frame(short_packet)
            EdlPacket.from_payload(frame, self.hmac_key)

    def test_unpack_invalid_fecf(self):
        """Test unpacking an EDL packet with an invalid FECF."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        edl_message_req = edl_packet_req.pack()
        frame = make_frame(edl_message_req, 0, 1, hmac_key=self.hmac_key)
        edl_message_req = frame.pack(frame_type=FrameType.VARIABLE)

        # Modifying FECF so that it is invalid
        edl_message_req = bytearray(edl_message_req)
        edl_message_req = edl_message_req[:-2] + b"\xff\xff"
        edl_message_req = bytes(edl_message_req)

        # Checking if UslpChecksumError exception is raised for the invalid FECF
        with self.assertRaises(UslpChecksumError):
             unpack_frame(edl_message_req)

    def test_unpack_invalid_hmac(self):
        """Test unpacking an EDL packet with an invalid HMAC."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        invalid_hmac = b"\0x12" * 32
        edl_message_req = edl_packet_req.pack()
        frame = make_frame(edl_message_req, 0, 1, hmac_key=invalid_hmac)

        with self.assertRaises(SdlsInvalidHmacError):
            verify_sdls(frame, self.hmac_key)

    def test_unpack_invalid_vcid(self):
        "Test unpacking an EDL packet with an invalid VCID."

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)

        class TestEnum(IntEnum):
            """Invalid enum for VCID"""

            INVALID = 20

        edl_packet_req.vcid = TestEnum.INVALID
        with self.assertRaises(IndexError and ValueError):
            make_frame(edl_packet_req.pack(), TestEnum.INVALID, 1, hmac_key=self.hmac_key)
