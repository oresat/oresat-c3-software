from dataclasses import dataclass

from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLenError
from spacepackets.uslp.frame import (
    FrameType,
    TransferFrame,
    VarFrameProperties,
)

SPACECRAFT_ID = 0x4F53  # aka "OS" in ASCII

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
)


class UslpInvalidSpacecraftIdError(Exception):
    pass

@dataclass
class Gvcid:
    """Global Virtual Channel Identifier

    CCSDS 732.1-B
    GVCID = TFVN + SCID + VCID

    Parameters
    ----------
    tfvn: int
        Transfer Frame Version Number. Must be 4 bits
    scid: int
        Spacecraft Identifier. Must be 16 bits
    vcid: int
        Virtual Channel Identifier. Must be 6 bits
    """

    tfvn: int  # 4 bits
    scid: int  # 16 bits
    vcid: int  # 6 bits

    def __post_init__(self):
        if not 0 <= self.tfvn <= 0xF:
            raise ValueError(f"TFVN must be 4 bits, got {self.tfvn}")
        if not 0 <= self.scid <= 0xFFFF:
            raise ValueError(f"SCID must be 16 bits, got {self.scid}")
        if not 0 <= self.vcid <= 0x3F:
            raise ValueError(f"VCID must be 6 bits, got {self.vcid}")

    def to_int(self) -> int:
        return (self.tfvn << 22) | (self.scid << 6) | self.vcid

    @classmethod
    def from_int(cls, value: int) -> "Gvcid":
        return cls(
            tfvn=(value >> 22) & 0xF,
            scid=(value >> 6)  & 0xFFFF,
            vcid= value        & 0x3F,
        )


def unpack_frame(raw: bytes) -> TransferFrame:
    """Unpack raw bytes into a valid TransferFrame

    Parameters
    ----------
    raw: bytes
        Raw bytes to unpack.

    Returns
    -------
    TransferFrame
        A valid TransferFrame.

    Raises
    ------
    UslpInvalidRawPacketOrFrameLenError
        If the packet is too short.
    UslpInvalidSpacecraftIdError
        The SCID of the packet does not match the spacecraft.
    UslpCheckSumError
        The FECF of the packet does not match the checksum.
    UslpTruncatedFrameNotAllowed
        Truncated frames are not allowed for variable frames.
    """

    # USLP Transfer Frame Validation
    # a) Must have expected TFVN: checked by TransferFrame.unpack
    # b) Must have expected MCID: checked below by also comparing SCID
    # c) Header consistent with implemented features: covered by FRAME_PROPS + unpack
    # d) Consistent number of octets: length check short-circuit with TC_MIN_LEN
    #    Individual frame fields are check by unpack
    # e) Computed CRC matches FECF: CRC is checked by unpack

    if len(raw) < TC_MIN_LEN:
        raise UslpInvalidRawPacketOrFrameLenError(f"Packet too short: {len(raw)}")
    frame = TransferFrame.unpack(raw, FrameType.VARIABLE, FRAME_PROPS)
    if frame.header.scid != SPACECRAFT_ID:
        raise UslpInvalidSpacecraftIdError

    return frame
