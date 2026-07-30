"""Unit tests for USLP frame construction and parsing."""

import unittest

from spacepackets.uslp.defs import UslpChecksumError, UslpInvalidRawPacketOrFrameLenError
from spacepackets.uslp.frame import FrameType

from oresat_c3.protocols.edl_packet import SRC_DEST_ORESAT, EdlVcid
from oresat_c3.protocols.uslp import make_frame, unpack_frame

HMAC_KEY = b"\x00" * 32


class TestMakeFrameUnpackFrame(unittest.TestCase):
    """Tests for making and unpacking USLP frames."""

    def _pack(self, frame):
        return frame.pack(frame_type=FrameType.VARIABLE)

    def test_ad_frame_roundtrip(self):
        """Type-AD frame packs and unpacks with correct checksum and SDLS."""
        frame = make_frame(
            b"\x01\x02\x03",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            vcf_count=42,
            sequence_number=5,
        )
        raw = self._pack(frame)
        unpacked = unpack_frame(raw)
        self.assertEqual(unpacked.header.vcid, EdlVcid.C3_COMMAND)
        self.assertIsNotNone(unpacked.insert_zone)
        self.assertTrue(unpacked.tfdf.tfdz.startswith(b"\x01\x02\x03"))

    def test_ad_frame_len_is_total_minus_one(self):
        """frame_len header field must equal total packed bytes minus one."""
        frame = make_frame(
            b"\x01\x02\x03",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            vcf_count=0,
        )
        raw = self._pack(frame)
        self.assertEqual(frame.header.frame_len, len(raw) - 1)

    def test_ad_frame_sdls(self):
        """Type-AD frames must have SDLS header."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            vcf_count=0,
        )
        self.assertIsNotNone(frame.insert_zone)

    def test_bc_frame_roundtrip(self):
        """Type-BC frame (no SDLS)."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            vcf_count=None,
            bypass=True,
            command=True,
        )
        raw = self._pack(frame)
        unpacked = unpack_frame(raw)
        self.assertEqual(unpacked.header.vcid, EdlVcid.C3_COMMAND)
        self.assertIsNone(unpacked.insert_zone)
        self.assertEqual(unpacked.tfdf.tfdz, b"\x00")

    def test_bc_frame_no_sdls(self):
        """Type-BC (command) frames must not have an SDLS header."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            bypass=True,
            command=True,
        )
        self.assertIsNone(frame.insert_zone)

    def test_bd_frame_has_sdls(self):
        """Type-BD frames must have an SDLS header."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            bypass=True,
            command=False,
        )
        self.assertIsNotNone(frame.insert_zone)

    def test_bd_frame_roundtrip(self):
        """Type-BD frame packs and unpacks correctly with SDLS."""
        frame = make_frame(
            b"\x01\x02",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            bypass=True,
            command=False,
            sequence_number=7,
        )
        raw = self._pack(frame)
        unpacked = unpack_frame(raw)
        self.assertEqual(unpacked.header.vcid, EdlVcid.C3_COMMAND)
        self.assertIsNotNone(unpacked.insert_zone)
        self.assertTrue(unpacked.tfdf.tfdz.startswith(b"\x01\x02"))

    def test_bc_frame_len_is_total_minus_one(self):
        """BC frame_len field must equal total packed bytes minus one."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            bypass=True,
            command=True,
        )
        raw = self._pack(frame)
        self.assertEqual(frame.header.frame_len, len(raw) - 1)

    def test_idle_frame_roundtrip(self):
        """IDLE frame (no SDLS, with CLCW) packing and unpacking."""
        clcw = b"\x00\x00\x00\x00"
        frame = make_frame(
            b"\x00",
            EdlVcid.IDLE,
            SRC_DEST_ORESAT,
            control_word=clcw,
        )
        raw = self._pack(frame)
        unpacked = unpack_frame(raw)
        self.assertEqual(unpacked.header.vcid, EdlVcid.IDLE)
        self.assertIsNone(unpacked.insert_zone)
        self.assertEqual(unpacked.op_ctrl_field, clcw)

    def test_ad_invalid_fecf_raises(self):
        """Invalid checksum (FECF) of a Type-AD frame must raise UslpChecksumError."""
        frame = make_frame(
            b"\xde\xad",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            hmac_key=HMAC_KEY,
            vcf_count=1,
        )
        raw = bytearray(self._pack(frame))
        raw[-1] ^= 0xFF
        with self.assertRaises(UslpChecksumError):
            unpack_frame(bytes(raw))

    def test_bc_invalid_fecf_raises(self):
        """Invalid checksum (FECF) of a Type-BC frame must raise UslpChecksumError."""
        frame = make_frame(
            b"\x00",
            EdlVcid.C3_COMMAND,
            SRC_DEST_ORESAT,
            bypass=True,
            command=True,
        )
        raw = bytearray(self._pack(frame))
        raw[-1] ^= 0xFF
        with self.assertRaises(UslpChecksumError):
            unpack_frame(bytes(raw))

    def test_too_short_raises(self):
        """Frames shorter than TC_MIN_LEN must raise UslpInvalidRawPacketOrFrameLenError."""
        from oresat_c3.protocols.uslp import TC_MIN_LEN

        with self.assertRaises(UslpInvalidRawPacketOrFrameLenError):
            unpack_frame(b"\x00" * (TC_MIN_LEN - 1))
