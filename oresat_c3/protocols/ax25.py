"""Anything dealing with packing AX.25 packets."""

from dataclasses import dataclass

import bitstring

AX25_CALLSIGN_LEN = 6
AX25_HEADER_LEN = 16
AX25_PAYLOAD_MAX_LEN = 256


class Ax25Error(Exception):
    """Error with ax25_pack"""


def ax25_pack(
    dest_callsign: str,
    dest_ssid: int,
    src_callsign: str,
    src_ssid: int,
    control: int,
    pid: int,
    command: bool,
    response: bool,
    payload: bytes,
) -> bytes:
    """
    Generate a AX25 packet.

    Parameters
    ----------
    dest_callsing: str
        The destination callsign. Must be 6 chars or less. If less that 6 chars, spaces will be
        appended as padding.
    dest_ssid: int
        The destination SSID (Secondary Station Identifier).
    src_callsign: str
        The source callsign. Must be 6 chars or less. If less that 6 chars, spaces will be appended
        as padding.
    src_ssid: int
        The source SSID (Secondary Station Identifier).
    control: int
        Control field value, defines type of frame being sent.
    pid: int
        Protocol Identifier field. It defines which Layer 3 protocol is in use.
    command: bool
        Set the c-bit in dest
    response: bool
        Set the c-bit in src
    payload: bytes
        Payload data

    Rasises
    -------
    Ax25Error
        On any error

    Returns
    -------
    bytes
        The AX25 packet.
    """

    if len(dest_callsign) > AX25_CALLSIGN_LEN:
        raise Ax25Error(f"dest callsign must be less than {AX25_CALLSIGN_LEN} chars")
    if dest_ssid < 0 or dest_ssid > 15:
        raise Ax25Error("dest callsign must be between 0 and 15")
    if len(src_callsign) > AX25_CALLSIGN_LEN:
        raise Ax25Error(f"src callsign must be less than {AX25_CALLSIGN_LEN} chars")
    if src_ssid < 0 or src_ssid > 15:
        raise Ax25Error("src callsign must be between 0 and 15")
    if len(payload) > AX25_PAYLOAD_MAX_LEN:
        raise Ax25Error(f"payload must be less than {AX25_PAYLOAD_MAX_LEN} bytes")
    if control < 0 or control > 0xFF:
        raise Ax25Error("control must fit into a uint8")
    if pid < 0 or pid > 0xFF:
        raise Ax25Error("pid must fit into a uint8")

    # callsigns must be 6 chars, add trailing spaces as padding
    dest_callsign += " " * (AX25_CALLSIGN_LEN - len(dest_callsign))
    src_callsign += " " * (AX25_CALLSIGN_LEN - len(src_callsign))

    # move ssid to bits 4-1
    dest_ssid <<= 1
    src_ssid <<= 1

    # set reserve bits
    reserve_bits = 0b0110_0000
    dest_ssid |= reserve_bits
    src_ssid |= reserve_bits

    # set the c-bits
    dest_ssid |= int(command) << 7
    src_ssid |= int(response) << 7

    # set end of address bit
    src_ssid |= 1

    # make AX25 packet header
    # callsigns are bitshifted by 1
    header = (
        (bitstring.BitArray(dest_callsign.encode()) << 1).bytes
        + dest_ssid.to_bytes(1, "little")
        + (bitstring.BitArray(src_callsign.encode()) << 1).bytes
        + src_ssid.to_bytes(1, "little")
        + control.to_bytes(1, "little")
        + pid.to_bytes(1, "little")
    )

    return header + payload


@dataclass
class Ax25:
    """Holds the contents of an AX.25 packet"""

    dest_callsign: str
    dest_ssid: int
    src_callsign: str
    src_ssid: int
    control: int
    pid: int
    command: bool
    response: bool
    payload: bytes


def ax25_unpack(raw: bytes) -> Ax25:
    """
    Unpacks a AX25 packet.

    Parameters
    ----------
    raw: bytes
        Raw bytes of an AX25 packet

    Returns
    -------
    AX25
        The AX25 fields.
    """
    # Unpack AX25 packet header
    dest = raw[:AX25_CALLSIGN_LEN]
    dest_ssid = raw[AX25_CALLSIGN_LEN]
    src = raw[AX25_CALLSIGN_LEN + 1 : 2 * AX25_CALLSIGN_LEN + 1]
    src_ssid = raw[2 * AX25_CALLSIGN_LEN + 1]
    control = raw[2 * AX25_CALLSIGN_LEN + 2]
    pid = raw[2 * AX25_CALLSIGN_LEN + 3]
    payload = raw[2 * AX25_CALLSIGN_LEN + 4 :]

    # callsigns are bitshifted by 1
    dest_callsign = (bitstring.BitArray(dest) >> 1).bytes.decode("ascii").rstrip()
    src_callsign = (bitstring.BitArray(src) >> 1).bytes.decode("ascii").rstrip()

    return Ax25(
        dest_callsign=dest_callsign,
        dest_ssid=(dest_ssid & 0x1F) >> 1,
        src_callsign=src_callsign,
        src_ssid=(src_ssid & 0x1F) >> 1,
        control=control,
        pid=pid,
        command=bool(dest_ssid & 1 << 7),
        response=bool(src_ssid & 1 << 7),
        payload=payload,
    )
