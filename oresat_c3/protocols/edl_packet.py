"""
Anything dealing with packing and unpacking EDL (Engineering Data Link) packets.
"""

import hashlib
import hmac
from enum import IntEnum
from typing import Optional, Union

from spacepackets.cfdp.pdu import PduFactory
from spacepackets.cfdp.pdu.file_directive import AbstractPduBase
from spacepackets.uslp.frame import (  # type: ignore
    FrameType,
    TfdzConstructionRules,
    TransferFrame,
    TransferFrameDataField,
    UslpProtocolIdentifier,
)
from spacepackets.uslp.header import (  # type: ignore
    BypassSequenceControlFlag,
    PrimaryHeader,
    ProtocolCommandFlag,
    SourceOrDestField,
)

from .edl_command import EdlCommandCode, EdlCommandError, EdlCommandRequest, EdlCommandResponse
from .uslp import HMAC_LEN, SEQ_NUM_LEN, SPACECRAFT_ID, TC_MIN_LEN

SRC_DEST_ORESAT = SourceOrDestField.DEST
SRC_DEST_UNICLOGS = SourceOrDestField.SOURCE


class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1


def gen_hmac(hmac_key: bytes, message: bytes) -> bytes:
    """Helper function to generate HMAC value from HMAC key and the message."""

    return hmac.digest(hmac_key, message, hashlib.sha3_256)


class EdlPacket:
    """
    An EDL (Engineering Data Link) packet.

    Only packs and unpacks the packet (does not process/run it).
    """

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

    def pack(self, hmac_key: bytes, control_word: Optional[bytes] = None) -> bytes:
        """
        Pack the EDL packet.

        Parameters
        ----------
        control_word : Optional[bytes]
            Send a control word with the frame.
        hmac_key: bytes
            The HMAC key to use.
        """

        try:
            payload_raw = self.payload.pack()
        except Exception as e:
            raise EdlPacketError(e) from e

        tfdz = payload_raw

        tfdf = TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=UslpProtocolIdentifier.MISSION_SPECIFIC_INFO_1_MAPA_SDU,
            tfdz=tfdz,
        )

        # USLP transfer frame total length - 1
        frame_len = len(payload_raw) + TC_MIN_LEN - 1
        trailer_end = frame_len

        has_clcw = bool(control_word)
        if has_clcw:
            frame_len += len(control_word)

        frame_header = PrimaryHeader(
            scid=SPACECRAFT_ID,
            map_id=0,
            vcid=self.vcid.value,
            src_dest=self.src_dest,
            frame_len=frame_len,
            vcf_count_len=0,
            op_ctrl_flag=has_clcw,
            prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
            bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        
        sdls_header_bytes = bytes(b"\x00\x01")
        sdls_header_bytes += self.seq_num.to_bytes(SEQ_NUM_LEN, "big")

        ### COMPUTE HMAC HERE

        authenticated_payload = frame_header.pack() + sdls_header_bytes + tfdf.pack()
        

        header_mask = bytearray(b"\x00\x00\x07\xfe\x00\x00\x00")
        # TODO: when the vc frame count lengths are not 0, this will need to change. this should not 
        # be a surprise, as there is probably a much better way to do this.
        for i in range(7):
            authenticated_payload[i] = authenticated_payload[i] & header_mask[i]

        print(hmac_key.hex())
        print(authenticated_payload.hex())

        # 00000000000000000100000000E51101000000
        # 00000000000000000100000000e51101000000

        hmac_val = gen_hmac(hmac_key, authenticated_payload)
        tfdz = tfdz + hmac_val

        tfdf = TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=UslpProtocolIdentifier.MISSION_SPECIFIC_INFO_1_MAPA_SDU,
            tfdz=tfdz,
        )

        frame = TransferFrame(
            header=frame_header, tfdf=tfdf, insert_zone=sdls_header_bytes, op_ctrl_field=control_word
        )

        packet = frame.pack(frame_type=FrameType.VARIABLE)


        return packet

    @classmethod
    def unpack(cls, frame: TransferFrame, hmac_key: bytes, ignore_hmac: bool = False):
        """
        Unpack the EDL packet.

        Parameters
        ----------
        frame : TransferFrame
            The frame to unpack.
        hmac_key: bytes
            The hmac key.
        ignore_hmac: bool
            Ignore the HMAC value.
        """

        payload_raw = frame.tfdf.tfdz[:-HMAC_LEN]
        hmac_bytes = frame.tfdf.tfdz[-HMAC_LEN:]
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
