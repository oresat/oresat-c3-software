"""
Anything dealing with packing and unpacking EDL (Engineering Data Link) packets.
"""

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
from .uslp import HMAC_LEN, SEQ_NUM_LEN, make_frame
from .sdls import verify_sdls

SRC_DEST_ORESAT = SourceOrDestField.DEST
SRC_DEST_UNICLOGS = SourceOrDestField.SOURCE


class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1



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

        frame = make_frame(
            payload=payload_raw,
            vcid=self.vcid.value,
            src_dest=self.src_dest,
            control_word=control_word,
            sequence_number=self.seq_num,
            hmac_key=hmac_key
        )
        return frame.pack(frame_type=FrameType.VARIABLE)

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

        seq_num = verify_sdls(frame, hmac_key)
        payload_raw = frame.tfdf.tfdz[:-HMAC_LEN]
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

        return EdlPacket(payload, seq_num, frame.header.src_dest)
