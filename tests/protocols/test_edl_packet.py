"""Unit tests for EdlPacket."""

import unittest
from enum import IntEnum

from spacepackets.uslp.defs import UslpChecksumError, UslpInvalidRawPacketOrFrameLenError

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandResponse
from oresat_c3.protocols.edl_packet import (
    SRC_DEST_ORESAT,
    SRC_DEST_UNICLOGS,
    EdlPacket,
    EdlPacketError,
)
from oresat_c3.protocols.uslp import TC_MIN_LEN, unpack_frame


class TestEdlPacket(unittest.TestCase):
    """Test the EdlPacket."""

    def setUp(self):
        self.hmac_key = b"\x00" * 128
        self.seq_num = 0

    def test_basic_pack_unpack(self):
        """Test packing and unpacking an EDL request packet and response packet."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        edl_message_req = edl_packet_req.pack(self.hmac_key)
        edl_packet_req2 = EdlPacket.from_frame(unpack_frame(edl_message_req), self.hmac_key)
        self.assertEqual(edl_packet_req, edl_packet_req2)

        payload = EdlCommandResponse(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_res = EdlPacket(payload, self.seq_num, SRC_DEST_UNICLOGS)
        edl_message_res = edl_packet_res.pack(self.hmac_key)
        edl_packet_res2 = EdlPacket.from_frame(unpack_frame(edl_message_res), self.hmac_key)
        self.assertEqual(edl_packet_res, edl_packet_res2)

    def test_unpack_short_packet(self):
        """Test unpacking an message that is to short to be a valid EDL packet."""

        # Preparing a packet that is shorter than the minimum length
        short_packet = b"\x00" * (TC_MIN_LEN - 1)

        # Test if EdlPacketError "Packet too short" exception is thrown
        with self.assertRaises(UslpInvalidRawPacketOrFrameLenError):
            frame = unpack_frame(short_packet)
            EdlPacket.from_frame(frame, self.hmac_key)

    def test_unpack_invalid_fecf(self):
        """Test unpacking an EDL packet with an invalid FECF."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        edl_message_req = edl_packet_req.pack(self.hmac_key)

        # Modifying FECF so that it is invalid
        edl_message_req = bytearray(edl_message_req)
        edl_message_req = edl_message_req[:-2] + b"\xff\xff"
        edl_message_req = bytes(edl_message_req)

        # Checking if UslpChecksumError exception is raised for the invalid FECF
        with self.assertRaises(UslpChecksumError):
            frame = unpack_frame(edl_message_req)
            EdlPacket.from_frame(frame, self.hmac_key)

    def test_unpack_invalid_hmac(self):
        """Test unpacking an EDL packet with an invalid HMAC."""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)
        invalid_hmac = b"\0x12" * 32
        edl_message_req = edl_packet_req.pack(invalid_hmac)

        frame = unpack_frame(edl_message_req)
        with self.assertRaises(EdlPacketError):
            EdlPacket.from_frame(frame, self.hmac_key)

    def test_unpack_invalid_vcid(self):
        "" "Test unpacking an EDL packet with an invalid VCID." ""

        payload = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        edl_packet_req = EdlPacket(payload, self.seq_num, SRC_DEST_ORESAT)

        class TestEnum(IntEnum):
            """Invalid enum for VCID"""

            INVALID = 20

        edl_packet_req.vcid = TestEnum.INVALID
        req = edl_packet_req.pack(self.hmac_key)

        frame = unpack_frame(req)
        with self.assertRaises(EdlPacketError):
            EdlPacket.from_frame(frame, self.hmac_key)
