import logging
import struct
import unittest

from spacepackets.uslp import (
    BypassSequenceControlFlag,
    PrimaryHeader,
    ProtocolCommandFlag,
    SourceOrDestField,
    TfdzConstructionRules,
    TransferFrame,
    TransferFrameDataField,
    UslpProtocolIdentifier,
)

from oresat_c3.protocols.cop1 import ControlWord, Farm1
from oresat_c3.protocols.edl_packet import EdlVcid
from oresat_c3.protocols.uslp import SPACECRAFT_ID, TC_MIN_LEN, Gvcid


class TestFarm1(unittest.TestCase):
    FRAME_TYPE_BC: TransferFrame
    FRAME_TYPE_BD: TransferFrame
    FRAME_TYPE_AD: TransferFrame
    INVALID_TYPE_BC: TransferFrame
    INVALID_TYPE_AC: TransferFrame

    INVALID_SEQ_FRAME: TransferFrame

    def setUp(self):
        self.farm1 = Farm1(w=254, allow_retransmission=True)

        def make_test_frame(
            payload,
            prot_ident: UslpProtocolIdentifier,
            prot_ctrl: ProtocolCommandFlag,
            bypass_ctrl: BypassSequenceControlFlag,
        ) -> TransferFrame:
            # USLP transfer frame total length - 1
            frame_len = len(payload) + TC_MIN_LEN - 1
            return TransferFrame(
                header=PrimaryHeader(
                    scid=SPACECRAFT_ID,
                    map_id=0,
                    vcid=EdlVcid.C3_COMMAND,
                    src_dest=SourceOrDestField.DEST,
                    frame_len=frame_len,
                    vcf_count_len=2,
                    vcf_count=0,
                    op_ctrl_flag=False,
                    prot_ctrl_cmd_flag=prot_ctrl,
                    bypass_seq_ctrl_flag=bypass_ctrl,
                ),
                tfdf=TransferFrameDataField(
                    tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
                    uslp_ident=prot_ident,
                    tfdz=payload,
                ),
            )

        payload_raw = b"\x82\x00\x05"  # set V(R) = 5
        self.FRAME_TYPE_BC = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.COP_1_CTRL_COMMANDS,
            ProtocolCommandFlag.PROTOCOL_INFORMATION,
            BypassSequenceControlFlag.EXPEDITED_QOS,
        )
        self.FRAME_TYPE_BD = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
            ProtocolCommandFlag.USER_DATA,
            BypassSequenceControlFlag.EXPEDITED_QOS,
        )
        self.FRAME_TYPE_AD = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
            ProtocolCommandFlag.USER_DATA,
            BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )
        self.INVALID_TYPE_BC = make_test_frame(
            b"\x01",
            UslpProtocolIdentifier.COP_1_CTRL_COMMANDS,
            ProtocolCommandFlag.PROTOCOL_INFORMATION,
            BypassSequenceControlFlag.EXPEDITED_QOS,
        )
        self.INVALID_TYPE_AC = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
            ProtocolCommandFlag.PROTOCOL_INFORMATION,
            BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        self.INVALID_SEQ_FRAME = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
            ProtocolCommandFlag.USER_DATA,
            BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

    def test_init(self):
        valid_w = 254
        valid_w_no_re = 256
        valid_pw = 256
        valid_nw = 0
        Farm1(valid_w, 0, 0, vcf_count_length=2, allow_retransmission=True)
        Farm1(valid_w_no_re, valid_pw, valid_nw, vcf_count_length=2, allow_retransmission=False)
        with self.assertRaises(ValueError):
            Farm1(500, 0, 0, vcf_count_length=2, allow_retransmission=True)
        with self.assertRaises(ValueError):
            Farm1(0, 0, 0, vcf_count_length=2, allow_retransmission=False)
        with self.assertRaises(ValueError):
            Farm1(valid_w_no_re, 0, 0, vcf_count_length=2, allow_retransmission=False)
        with self.assertRaises(ValueError):
            Farm1(valid_w_no_re, valid_pw, -1, vcf_count_length=2, allow_retransmission=False)

    def test_process_bc(self):
        self.assertTrue(self.farm1._process_frame(self.FRAME_TYPE_BC))
        self.assertEqual(self.farm1.b_counter, 1)
        self.assertFalse(self.farm1.retransmit)
        self.assertEqual(self.farm1.receiver_frame_sequence_number, 5)
        self.assertEqual(self.farm1.state, Farm1.FarmState.OPEN)

    def test_process_invalid_bc(self):
        self.assertFalse(self.farm1._process_frame(self.INVALID_TYPE_BC))

    def test_process_bd(self):
        self.assertTrue(self.farm1._process_frame(self.FRAME_TYPE_BD))
        indication = self.farm1.higher_interface.signal.pop()
        self.assertIsInstance(indication, Farm1.FduArrivedIndication)
        self.farm1.higher_interface.buffer.pop()

    def test_process_ad(self):
        self.assertTrue(self.farm1._process_frame(self.FRAME_TYPE_AD))
        self.assertEqual(self.farm1.receiver_frame_sequence_number, 1)
        self.assertEqual(len(self.farm1.higher_interface.buffer), 1)

    def test_process_ac(self):
        self.assertFalse(self.farm1._process_frame(self.INVALID_TYPE_AC))

    def test_buffer_put(self):
        self.farm1.lower_interface.buffer.append(self.FRAME_TYPE_BC)
        self.assertEqual(len(self.farm1.lower_interface.buffer), 1)

    def test_notify(self):
        gvcid = Gvcid(0b1100, self.FRAME_TYPE_BC.header.scid, self.FRAME_TYPE_BC.header.vcid)
        self.farm1.lower_interface.signal.append(Farm1.ValidFrameArrivedIndication(gvcid))
        self.assertEqual(len(self.farm1.lower_interface.signal), 1)

    def test_trigger_retransmit(self):
        # set V(R) to predictable value first
        self.assertTrue(self.farm1._process_frame(self.FRAME_TYPE_BC))
        invalid_ns = (
            self.farm1.receiver_frame_sequence_number
            + (self.farm1.receiver_frame_sequence_number + self.farm1.positive_window_width - 1)
            // 2
        )
        self.assertTrue(
            self.farm1.receiver_frame_sequence_number
            < invalid_ns
            <= self.farm1.receiver_frame_sequence_number + self.farm1.positive_window_width - 1,
            msg="Failed to calculate invalid N(S) sequence number for this test",
        )
        self.INVALID_SEQ_FRAME.header.vcf_count = invalid_ns
        self.assertFalse(self.farm1._process_frame(self.INVALID_SEQ_FRAME))
        self.assertTrue(self.farm1.retransmit)

    def test_lockout(self):
        self.farm1.receiver_frame_sequence_number = 0
        self.INVALID_SEQ_FRAME.header.vcf_count = self.farm1.sliding_window_width // 2
        self.assertFalse(self.farm1._process_frame(self.INVALID_SEQ_FRAME))
        self.assertTrue(self.farm1.lockout)

    def test_large_vcf(self):
        # weirdness may happen if modulo arithmetic is not respected
        # see the note under CCSDS 232.1-B-2 6.2.1 GENERAL
        # set V(R) to predictable value first
        self.assertTrue(self.farm1._process_frame(self.FRAME_TYPE_BC))
        self.INVALID_SEQ_FRAME.header.vcf_count = 60000
        self.assertFalse(self.farm1._process_frame(self.INVALID_SEQ_FRAME))


class TestClcw(unittest.TestCase):
    def test_pack_length(self):
        self.assertEqual(len(ControlWord().pack()), 4)

    def test_default_roundtrip(self):
        clcw = ControlWord()
        self.assertEqual(ControlWord.unpack(clcw.pack()), clcw)

    def test_field_roundtrip(self):
        clcw = ControlWord(
            status_field=0b101,
            cop_in_effect=1,
            vcid=0x3F,
            no_rf_available=True,
            no_bit_lock=True,
            lockout=True,
            wait=True,
            retransmit=True,
            farm_b_counter=3,
            report_value=0xAB,
        )
        self.assertEqual(ControlWord.unpack(clcw.pack()), clcw)

    def test_reserved_spares_are_zero(self):
        # bits 16-17 and bit 8 must always be zero regardless of field values
        clcw = ControlWord(vcid=0x3F, report_value=0xFF)
        (word,) = struct.unpack(">I", clcw.pack())
        self.assertEqual((word >> 16) & 0x3, 0)
        self.assertEqual((word >> 8) & 0x1, 0)

    def test_flags_isolated(self):
        for attr, bit in [
            ("no_rf_available", 15),
            ("no_bit_lock", 14),
            ("lockout", 13),
            ("wait", 12),
            ("retransmit", 11),
        ]:
            clcw = ControlWord(**{attr: True})
            (word,) = struct.unpack(">I", clcw.pack())
            self.assertEqual((word >> bit) & 0x1, 1, msg=f"{attr} not set at bit {bit}")
            other_flags = 0x1F & ~(1 << (bit - 11))
            self.assertEqual((word >> 11) & other_flags, 0, msg=f"extra flag bits set for {attr}")

    def test_unpack_too_short_raises(self):
        with self.assertRaises(ValueError):
            ControlWord.unpack(b"\x00\x00\x00")

    def test_unpack_ignores_reserved_spare_bits(self):
        # reserved spare bits set in raw bytes should not bleed into named fields
        raw = struct.pack(">I", 0x0003_0100)  # spare bits 16-17 and bit 8 all set
        clcw = ControlWord.unpack(raw)
        self.assertEqual(clcw.report_value, 0)
        self.assertFalse(clcw.retransmit)
