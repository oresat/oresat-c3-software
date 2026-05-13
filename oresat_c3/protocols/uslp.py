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
    vcf_count: Optional[int] = None,
    control_word: Optional[bytes] = None,
    insert_zone: Optional[bytes] = None,
) -> TransferFrame:
    """Create and pack a USLP

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
    insert_zone
        The insert zone data, if any.

    Returns
    -------
    TransferFrame
        The constructed Transfer Frame.
    """

    tfdf = TransferFrameDataField(
        tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
        uslp_ident=UslpProtocolIdentifier.USER_DEFINED_OCTET_STREAM,
        tfdz=payload,
    )

    # USLP transfer frame total length - 1
    frame_len = len(payload) + PRIMARY_HEADER_LEN + DFH_LEN + FECF_LEN - 1
    if insert_zone:
        frame_len += len(insert_zone)

    has_clcw = bool(control_word)
    if has_clcw:
        frame_len += len(control_word)

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

    return TransferFrame(
        header=frame_header, tfdf=tfdf, op_ctrl_field=control_word, insert_zone=insert_zone
    )
