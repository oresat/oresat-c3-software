'''
Anything dealing with packing and unpacking EDL (Engineering Data Link) C3 command packets.

These package are defined as 1 octect for code and X octects for the data.

The EDL code is used to identify the message the rest of message is for argument for
request, and values for responeses.
'''

import binascii
import hashlib
import hmac
from enum import IntEnum

from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLen
from spacepackets.uslp.frame import TransferFrame, TransferFrameDataField, TfdzConstructionRules, \
    UslpProtocolIdentifier, VarFrameProperties, FrameType
from spacepackets.uslp.header import PrimaryHeader, SourceOrDestField, ProtocolCommandFlag, \
    BypassSequenceControlFlag

from .edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandRespone

SRC_DEST_ORESAT = SourceOrDestField.SOURCE
SRC_DEST_UNICLOGS = SourceOrDestField.DEST


class EdlError(Exception):
    '''Error with EdlBase'''


class EdlVcid(IntEnum):
    '''USLP virtual channel IDs for EDL packets'''

    C3_COMMAND = 0
    FILE_TRANSFER = 1


def crc16_bytes(data: bytes) -> bytes:
    '''Helper function for generating the crc16 of a message as bytes'''

    return binascii.crc_hqx(data, 0).to_bytes(2, 'little')


def gen_hmac(hmac_key, message: bytes) -> bytes:

    return hmac.digest(hmac_key, message, hashlib.sha3_256)


class EdlPacket:
    '''
    An EDL (Engineering Data Link) packet.

    Only packs and unpacks the packet (does not process/run it).
    '''

    SPACECRAFT_ID = 0x4F53  # aka "OS" in ascii

    PRIMARY_HEADER_LEN = 7
    SEQ_NUM_LEN = 4
    DFH_LEN = 1
    HMAC_LEN = 32
    FECF_LEN = 2
    _TC_MIN_LEN = PRIMARY_HEADER_LEN + SEQ_NUM_LEN + DFH_LEN + HMAC_LEN + FECF_LEN

    FRAME_PROPS = VarFrameProperties(
        has_insert_zone=True,
        has_fecf=True,
        truncated_frame_len=0,
        insert_zone_len=SEQ_NUM_LEN,
        fecf_len=FECF_LEN,
    )

    def __init__(self, payload: EdlCommandRequest or EdlCommandRespone, seq_num: int,
                 src_dest: SourceOrDestField) -> bytes:
        '''
        Parameters
        ----------
        payload: EdlCommandRequest or EdlCommandRespone
            The payload object.
        seq_num: int
            The sequence number for packet.
        src_dest: SourceOrDestFiedld
            Origin of packet, use `SRC_DEST_ORESAT` or `SRC_DEST_UNICLOGS`.
        '''

        if isinstance(payload, EdlCommandRequest) or isinstance(payload, EdlCommandRespone):
            vcid = EdlVcid.C3_COMMAND
        else:
            raise EdlCommandCode(f'unknown payload object: {type(payload)}')

        self.vcid = vcid
        self.src_dest = src_dest
        self.seq_num = seq_num
        self.payload = payload

    def pack(self, hmac_key: bytes) -> bytes:
        '''
        Pack the EDL packet.

        Parameters
        ----------
        hmac_key: bytes
            The HMAC key to use.
        '''

        payload_raw = self.payload.pack()
        tfdz = payload_raw + gen_hmac(hmac_key, payload_raw)

        tfdf = TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=UslpProtocolIdentifier.MISSION_SPECIFIC_INFO_1_MAPA_SDU,
            tfdz=tfdz,
        )

        # USLP transfer frame total length - 1
        frame_len = len(payload_raw) + self.TC_MIN_LEN - 1

        frame_header = PrimaryHeader(
            scid=self.SPACECRAFT_ID,
            map_id=0,
            vcid=self.vcid,
            src_dest=self.src_dest,
            frame_len=frame_len,
            vcf_count_len=0,
            op_ctrl_flag=False,
            prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
            bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        seq_num_bytes = self.seq_num.to_bytes(self.SEQ_NUM_LEN, 'little')
        frame = TransferFrame(header=frame_header, tfdf=tfdf, insert_zone=seq_num_bytes)
        packet = frame.pack(frame_type=FrameType.VARIABLE)
        packet += crc16_bytes(packet)

        return packet

    @classmethod
    def unpack(cls, raw: bytes):
        '''
        Unpack the EDL packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        '''

        if len(raw) < cls._TC_MIN_LEN:
            raise EdlError(f'EDL packet too short: {len(raw)}')

        crc16_raw = raw[-cls.FECF_LEN:]
        crc16_raw_calc = crc16_bytes(raw[:-cls.FECF_LEN])
        if crc16_raw_calc != crc16_raw:
            raise EdlError(f'invalid FECF: {crc16_raw} vs {crc16_raw_calc}')

        try:
            frame = TransferFrame.unpack(raw, FrameType.VARIABLE, cls.FRAME_PROPS)
        except UslpInvalidRawPacketOrFrameLen:
            raise EdlError('USLP invalid packet or frame length')

        payload_raw = frame.tfdf.tfdz[:-cls.HMAC_LEN]
        hmac_bytes = frame.tfdf.tfdz[-cls.HMAC_LEN:]
        hmac_bytes_calc = gen_hmac(payload_raw)

        if hmac_bytes != hmac_bytes_calc:
            raise EdlError(f'invalid HMAC {hmac_bytes.hex()} vs {hmac_bytes_calc.hex()}')

        if frame.header.vcid == EdlVcid.C3_COMMAND:
            if frame.header.src_dest == SRC_DEST_ORESAT:
                payload = EdlCommandRequest.unpack(payload_raw)
            else:
                payload = EdlCommandRespone.unpack(payload_raw)
        else:
            raise EdlCommandCode(f'unknown vcid {frame.header.vcid}')

        seq_num = int.from_bytes(frame.insert_zone, 'little')

        return cls.__init__(payload, seq_num, frame.header.src_dest)
