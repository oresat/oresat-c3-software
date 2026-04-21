import unittest

from spacepackets.uslp import (
    TransferFrame,
    TransferFrameDataField,
    TfdzConstructionRules,
    UslpProtocolIdentifier,
    PrimaryHeader,
    SourceOrDestField,
    ProtocolCommandFlag,
    BypassSequenceControlFlag,
)

from oresat_c3.protocols.cop1 import Farm1
from oresat_c3.protocols.edl_packet import EdlPacket, EdlVcid
from oresat_c3.protocols.uslp import Gvcid


class TestFarm1(unittest.TestCase):
    FRAME_TYPE_BC: TransferFrame
    FRAME_TYPE_BD: TransferFrame
    FRAME_TYPE_AD: TransferFrame
    INVALID_TYPE_AC: TransferFrame

    def setUp(self):
        self.farm1 = Farm1(
            w=254,
            allow_retransmission=True
        )

        def make_test_frame(
            payload,
            prot_ident: UslpProtocolIdentifier,
            prot_ctrl: ProtocolCommandFlag,
            bypass_ctrl: BypassSequenceControlFlag,
        ) -> TransferFrame:
            # USLP transfer frame total length - 1
            frame_len = len(payload) + EdlPacket.TC_MIN_LEN - 1
            return TransferFrame(
                header=PrimaryHeader(
                    scid=EdlPacket.SPACECRAFT_ID,
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
        self.INVALID_TYPE_AC = make_test_frame(
            payload_raw,
            UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
            ProtocolCommandFlag.PROTOCOL_INFORMATION,
            BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

    def tearDown(self):
        return
        self.farm1._thread.join()

    def test_init(self):
        valid_w = 254
        valid_w_no_re = 256
        valid_pw = 256
        valid_nw = 0
        Farm1(valid_w, 0, 0, True)
        Farm1(valid_w_no_re, valid_pw, valid_nw, False)
        with self.assertRaises(ValueError):
            Farm1(500, 0, 0, True)
        with self.assertRaises(ValueError):
            Farm1(0, 0, 0, False)
        with self.assertRaises(ValueError):
            Farm1(valid_w_no_re, 0, 0, False)
        with self.assertRaises(ValueError):
            Farm1(valid_w_no_re, valid_pw, -1, False)

    def test_process_bc(self):
        self.farm1._process_frame(self.FRAME_TYPE_BC)
        self.assertEqual(self.farm1.b_counter, 1)
        self.assertFalse(self.farm1.retransmit)
        self.assertEqual(self.farm1.receiver_frame_sequence_number, 5)
        self.assertEqual(self.farm1.state, Farm1.FarmState.OPEN)

    def test_process_bd(self):
        def cb(indication: object) -> None:
            self.assertIsInstance(indication, Farm1.FduArrivedIndication)
        self.farm1.register_callback(cb)
        self.farm1._process_frame(self.FRAME_TYPE_BD)
        self.farm1._out_buffer.get_nowait()

    def test_process_ad(self):
        self.farm1._process_frame(self.FRAME_TYPE_AD)
        self.assertEqual(self.farm1.receiver_frame_sequence_number, 1)
        self.assertEqual(self.farm1._out_buffer.qsize(), 1)

    def test_process_ac(self):
        self.farm1._process_frame(self.INVALID_TYPE_AC)

    def test_buffer_put(self):
        self.farm1.buffer_put(self.FRAME_TYPE_BC)
        self.assertEqual(self.farm1._recv_buffer.qsize(), 1)

    def test_notify(self):
        gvcid = Gvcid(0b1100, self.FRAME_TYPE_BC.header.scid, self.FRAME_TYPE_BC.header.vcid)
        self.farm1.notify(Farm1.ValidFrameArrivedIndication(gvcid))
        self.assertEqual(self.farm1._signals.qsize(), 1)
