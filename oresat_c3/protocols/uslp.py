from dataclasses import dataclass
from typing import Optional

from spacepackets.uslp import (
    BypassSequenceControlFlag,
    PrimaryHeader,
    ProtocolCommandFlag,
    SourceOrDestField,
)
from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLenError
from spacepackets.uslp.frame import (
    FrameType,
    TfdzConstructionRules,
    TransferFrame,
    TransferFrameDataField,
    UslpProtocolIdentifier,
    VarFrameProperties,
)
from .sdls import get_sdls_len, apply_sdls

SPACECRAFT_ID = 0x4F53  # aka "OS" in ASCII

PRIMARY_HEADER_LEN = 7
SEQ_NUM_LEN = 4 # no longer relevant to this, as it is handled instead by SDLS.
DFH_LEN = 1
HMAC_LEN = 32 # no longer relevant to this, as it is handled instead by SDLS.
FECF_LEN = 2
TC_MIN_LEN = PRIMARY_HEADER_LEN + DFH_LEN + FECF_LEN

FRAME_PROPS = VarFrameProperties(
    has_insert_zone=True,
    has_fecf=True,
    truncated_frame_len=0,
    insert_zone_len=6, #hardcoded for now. Bad. Fix.
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
            scid=(value >> 6) & 0xFFFF,
            vcid=value & 0x3F,
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


def make_frame(
    payload: bytes,
    vcid: int,
    src_dest: SourceOrDestField,
    hmac_key: bytes,
    vcf_count: Optional[int] = None,
    control_word: Optional[bytes] = None,
    sequence_number: int = 0,
) -> TransferFrame:
    """Create and pack a USLP Transfer Frame.

    Parameters
    ----------
    payload
        The pre-packed payload.
    vcid
        The Virtual Channel Identifier of the frame.
    src_dest
        The Source or Destination identifier.
    vcf_count
        The Virtual Channel Frame count. If None, the VCF length is to 0 and no count is specified.
    control_word
        The CLCW, if any, to pack in the frame.
    sequence_number
        The anti-replay sequence number for SDLS.
    hmac_key
        The key used for SDLS

    Returns
    -------
    TransferFrame
        The constructed Transfer Frame.
    """


    # Steps:
    # make the data field
    # Pass the vcid, sequence number into SDLS to get the "insert zone" that is actually the SDLS header.
    # get the length
    #  Pass the vcid into SDLS to get the MAC length
    # get the header
    #  Pass the header, SDLS header, and data zone into SDLS. Plan is for this to be turned into the HMAC, or encrypt the data zone if thats a thing I can do.
    # generate the frame

    tfdf = TransferFrameDataField(
        tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
        uslp_ident=UslpProtocolIdentifier.SPACE_PACKETS_ENCAPSULATION_PACKETS, # Needs to be this, otherwise we would need to rewrite at least 1000 lines in YAMCS for 5 bits.
        tfdz=payload,
    )

    has_clcw = bool(control_word)

    # USLP transfer frame total length - 1
    frame_len = len(payload) + PRIMARY_HEADER_LEN + DFH_LEN + FECF_LEN - 1
    if has_clcw:
        frame_len += len(control_word)
    frame_len += get_sdls_len(vcid)

    frame_header = PrimaryHeader(
        scid=SPACECRAFT_ID,
        map_id=0,
        vcid=vcid,
        src_dest=src_dest,
        frame_len=frame_len,
        vcf_count_len=bool(vcf_count),
        vcf_count=vcf_count,
        op_ctrl_flag=has_clcw,
        prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
        bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
    )

    sdls_header = apply_sdls(frame_header, sequence_number, tfdf, hmac_key)

    return TransferFrame(
        header=frame_header, tfdf=tfdf, op_ctrl_field=control_word, insert_zone=sdls_header
    )
