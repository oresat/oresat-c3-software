"""
Anything dealing with packing and unpacking EDL (Engineering Data Link) packets.
"""

import binascii
import hashlib
import hmac
from enum import IntEnum
from typing import Union

from spacepackets.cfdp.pdu import PduFactory
from spacepackets.cfdp.pdu.file_directive import AbstractPduBase
from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLen  # type: ignore
from spacepackets.uslp.frame import (  # type: ignore
    FrameType,
    TfdzConstructionRules,
    TransferFrame,
    TransferFrameDataField,
    UslpProtocolIdentifier,
    VarFrameProperties,
)
from spacepackets.uslp.header import (  # type: ignore
    BypassSequenceControlFlag,
    PrimaryHeader,
    ProtocolCommandFlag,
    SourceOrDestField,
)

from .edl_command import EdlCommandCode, EdlCommandError, EdlCommandRequest, EdlCommandResponse

SRC_DEST_ORESAT = SourceOrDestField.DEST
SRC_DEST_UNICLOGS = SourceOrDestField.SOURCE


class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1


def crc16_bytes(data: bytes) -> bytes:
    """Helper function to generate the crc16 of a message as bytes"""

    return binascii.crc_hqx(data, 0).to_bytes(2, "little")


def gen_hmac(hmac_key: bytes, message: bytes) -> bytes:
    """Helper function to generate HMAC value from HMAC key and the message."""

    return hmac.digest(hmac_key, message, hashlib.sha3_256)


class EdlPacket:
    """
    An EDL (Engineering Data Link) packet.

    Only packs and unpacks the packet (does not process/run it).
    """

    SPACECRAFT_ID = 0x4F53  # aka "OS" in ascii

    PRIMARY_HEADER_LEN = 7
    SEQ_NUM_LEN = 4
    DFH_LEN = 1
    HMAC_LEN = 32
    FECF_LEN = 2
    TC_MIN_LEN = PRIMARY_HEADER_LEN + SEQ_NUM_LEN + DFH_LEN + HMAC_LEN + FECF_LEN

    FRAME_PROPS = VarFrameProperties(
        has_insert_zone=True,
        has_fecf=True,
        truncated_frame_len=0,
        insert_zone_len=SEQ_NUM_LEN,
        fecf_len=FECF_LEN,
    )

    def __init__(
        self,
        payload: Union[EdlCommandRequest, EdlCommandResponse, AbstractPduBase],
        seq_num: int,
        src_dest: SourceOrDestField,
    ):
        """
        Parameters
        ----------
        payload: EdlCommandRequest, EdlCommandResponse, or AbstractPduBase
            The payload object.
        seq_num: int
            The sequence number for packet.
        src_dest: SourceOrDestFiedld
            Origin of packet, use `SRC_DEST_ORESAT` or `SRC_DEST_UNICLOGS`.
        """

        if isinstance(payload, (EdlCommandRequest, EdlCommandResponse)):
            vcid = EdlVcid.C3_COMMAND
        elif isinstance(payload, AbstractPduBase):
            vcid = EdlVcid.FILE_TRANSFER
        else:
            raise EdlCommandCode(f"unknown payload object: {type(payload)}")

        self.vcid = vcid
        self.src_dest = src_dest
        self.seq_num = seq_num
        self.payload = payload

    def __eq__(self, other) -> bool:
        if not isinstance(other, EdlPacket):
            return False
        return (
            self.vcid == other.vcid
            and self.src_dest == other.src_dest
            and self.seq_num == other.seq_num
            and self.payload == other.payload
        )

    def pack(self, hmac_key: bytes) -> bytes:
        """
        Pack the EDL packet.

        Parameters
        ----------
        hmac_key: bytes
            The HMAC key to use.
        """

        try:
            payload_raw = self.payload.pack()
        except Exception as e:
            raise EdlPacketError(e) from e

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
            vcid=self.vcid.value,
            src_dest=self.src_dest,
            frame_len=frame_len,
            vcf_count_len=0,
            op_ctrl_flag=False,
            prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
            bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        seq_num_bytes = self.seq_num.to_bytes(self.SEQ_NUM_LEN, "little")
        frame = TransferFrame(header=frame_header, tfdf=tfdf, insert_zone=seq_num_bytes)
        packet = frame.pack(frame_type=FrameType.VARIABLE)
        packet += crc16_bytes(packet)

        return packet

    @classmethod
    def unpack(cls, raw: bytes, hmac_key: bytes, ignore_hmac: bool = False):
        """
        Unpack the EDL packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        hmac_key: bytes
            The hmac key.
        ignore_hmac: bool
            Ignore the HMAC value.
        """

        if len(raw) < cls.TC_MIN_LEN:
            raise EdlPacketError(f"EDL packet too short: {len(raw)}")

        crc16_raw = raw[-cls.FECF_LEN :]
        crc16_raw_calc = crc16_bytes(raw[: -cls.FECF_LEN])
        if crc16_raw_calc != crc16_raw:
            raise EdlPacketError(f"invalid FECF: {crc16_raw.hex()} vs {crc16_raw_calc.hex()}")

        try:
            frame = TransferFrame.unpack(raw, FrameType.VARIABLE, cls.FRAME_PROPS)
        except UslpInvalidRawPacketOrFrameLen as e:
            raise EdlPacketError("USLP invalid packet or frame length") from e

        payload_raw = frame.tfdf.tfdz[: -cls.HMAC_LEN]
        hmac_bytes = frame.tfdf.tfdz[-cls.HMAC_LEN :]
        hmac_bytes_calc = gen_hmac(hmac_key, payload_raw)

        if not ignore_hmac and hmac_bytes != hmac_bytes_calc:
            raise EdlPacketError(f"invalid HMAC {hmac_bytes.hex()} vs {hmac_bytes_calc.hex()}")

        if frame.header.vcid == EdlVcid.C3_COMMAND:
            try:
                if frame.header.src_dest == SRC_DEST_ORESAT:
                    payload = EdlCommandRequest.unpack(payload_raw)
                else:
                    payload = EdlCommandResponse.unpack(payload_raw)
            except EdlCommandError as e:
                raise EdlPacketError(e) from e
        elif frame.header.vcid == EdlVcid.FILE_TRANSFER:
            try:
                payload = PduFactory.from_raw(payload_raw)
            except ValueError as e:
                raise EdlPacketError(e) from e
        else:
            raise EdlPacketError(f"unknown vcid {frame.header.vcid}")

        seq_num = int.from_bytes(frame.insert_zone, "little")

        return EdlPacket(payload, seq_num, frame.header.src_dest)
