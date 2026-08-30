"""
Anything dealing with packing and unpacking EDL (Engineering Data Link) packets.
"""

from enum import IntEnum
from typing import Union

from spacepackets.cfdp.pdu import PduFactory
from spacepackets.cfdp.pdu.file_directive import AbstractPduBase
from spacepackets.uslp.header import SourceOrDestField

from .edl_command import EdlCommandError, EdlCommandRequest, EdlCommandResponse

SRC_DEST_ORESAT = SourceOrDestField.DEST
SRC_DEST_UNICLOGS = SourceOrDestField.SOURCE


class EdlPacketError(Exception):
    """Error with EdlPacket"""


class EdlVcid(IntEnum):
    """USLP virtual channel IDs for EDL packets"""

    C3_COMMAND = 0
    FILE_TRANSFER = 1
    IDLE = 2


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
            raise EdlPacketError(f"unknown payload object: {type(payload)}")

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

    def pack(self) -> bytes:
        """Pack the EDL packet."""

        try:
            payload_raw = self.payload.pack()
            return payload_raw
        except Exception as e:
            raise EdlPacketError(e) from e

    @classmethod
    def from_frame(cls, payload_raw: bytes, vcid: EdlVcid, src_dest):
        """
        Unpack the EDL packet.

        Parameters
        ----------
        src_dest
        vcid
        payload_raw
        """

        if vcid == EdlVcid.C3_COMMAND:
            try:
                if src_dest == SRC_DEST_ORESAT:
                    payload = EdlCommandRequest.unpack(payload_raw)
                else:
                    payload = EdlCommandResponse.unpack(payload_raw)
            except EdlCommandError as e:
                raise EdlPacketError(e) from e
        elif vcid == EdlVcid.FILE_TRANSFER:
            try:
                payload = PduFactory.from_raw(payload_raw)
            except ValueError as e:
                raise EdlPacketError(e) from e
        else:
            raise EdlPacketError(f"unknown vcid {vcid}")

        return EdlPacket(payload, 0, src_dest)
