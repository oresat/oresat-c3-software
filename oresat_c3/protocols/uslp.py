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

from .sdls import apply_sdls, get_sdls_header_len, get_sdls_len

SPACECRAFT_ID = 0x4F53  # aka "OS" in ASCII

PRIMARY_HEADER_LEN = 7
DFH_LEN = 1
FECF_LEN = 2
TC_MIN_LEN = PRIMARY_HEADER_LEN + DFH_LEN + FECF_LEN


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

    vcid = ((raw[2] & 0b111) << 3) | ((raw[3] >> 5) & 0b111)

    is_command = bool(raw[6] & 0x40)
    sdls_header_len = 0 if is_command else get_sdls_header_len(vcid)

    frame_props = VarFrameProperties(
        has_insert_zone=sdls_header_len != 0,
        has_fecf=True,
        truncated_frame_len=0,
        insert_zone_len=sdls_header_len,
    )

    if len(raw) < TC_MIN_LEN:
        raise UslpInvalidRawPacketOrFrameLenError(f"Packet too short: {len(raw)}")
    frame = TransferFrame.unpack(raw, FrameType.VARIABLE, frame_props)
    if frame.header.scid != SPACECRAFT_ID:
        raise UslpInvalidSpacecraftIdError

    return frame


def make_frame(
    payload: bytes,
    vcid: int,
    src_dest: SourceOrDestField,
    hmac_key: Optional[bytes] = None,
    vcf_count: Optional[int] = None,
    control_word: Optional[bytes] = None,
    sequence_number: int = 0,
    bypass: bool = False,
    command: bool = False,
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
    hmac_key: bytes,
        The key used to authenticate the message.
    vcf_count
        The Virtual Channel Frame count. If None, the VCF length is to 0 and no count is specified.
    control_word
        The CLCW, if any, to pack in the frame.
    sequence_number
        The anti-replay sequence number for SDLS.
    bypass
        Specify if this frame is bypass (Type-BD) frame.
    command
        Specify if this frame is for protocol command.

    Returns
    -------
    TransferFrame
        The constructed Transfer Frame.
    """

    tfdf = TransferFrameDataField(
        tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
        uslp_ident=UslpProtocolIdentifier.SPACE_PACKETS_ENCAPSULATION_PACKETS,
        # Needs to be this, yamcs does not support user defined octet stream and this functions.
        tfdz=payload,
    )

    vcf_count_len = 1 if vcf_count is not None else 0

    has_clcw = control_word is not None

    # USLP transfer frame total length - 1
    frame_len = len(payload) + PRIMARY_HEADER_LEN + vcf_count_len + DFH_LEN + FECF_LEN - 1
    if has_clcw:
        frame_len += len(control_word)
    if not command:
        frame_len += get_sdls_len(vcid)

    frame_header = PrimaryHeader(
        scid=SPACECRAFT_ID,
        map_id=0,
        vcid=vcid,
        src_dest=src_dest,
        frame_len=frame_len,
        vcf_count_len=vcf_count_len,
        vcf_count=vcf_count,
        op_ctrl_flag=has_clcw,
        prot_ctrl_cmd_flag=(
            ProtocolCommandFlag.PROTOCOL_INFORMATION if command else ProtocolCommandFlag.USER_DATA
        ),
        bypass_seq_ctrl_flag=(
            BypassSequenceControlFlag.EXPEDITED_QOS
            if bypass
            else BypassSequenceControlFlag.SEQ_CTRLD_QOS
        ),
    )

    frame = TransferFrame(header=frame_header, tfdf=tfdf, op_ctrl_field=control_word)

    if not command:
        apply_sdls(frame, sequence_number, hmac_key)

    return frame
