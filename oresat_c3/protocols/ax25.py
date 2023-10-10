import zlib

import bitstring

AX25_CALLSIGN_LEN = 6
AX25_HEADER_LEN = 16
AX25_PAYLOAD_MAX_LEN = 255


class Ax25Error(Exception):
    """Error with ax25_pack"""


def ax25_pack(
    dest: str,
    dest_ssid: int,
    src: str,
    src_ssid: int,
    control: int,
    pid: int,
    payload: bytes,
    crc32: bool = True,
) -> bytes:
    """
    Generate a AX25 packet.

    Parameters
    ----------
    dest: str
        The destination callsign. Must be 6 chars or less. If less that 6 chars, spaces will be
        appended as padding.
    dest_ssid: int
        The destination SSID (Secondary Station Identifier). Must be between 0 and 15.
    src: str
        The source callsign. Must be 6 chars or less. If less that 6 chars, spaces will be appended
        as padding.
    src_ssid: int
        The source SSID (Secondary Station Identifier). Must be between 0 and 15.
    control: int
        Control field value, defines type of frame being sent.
    pid: int
        Protocol Identifier field. It defines which Layer 3 protocol is in use.
    payload: bytes
        Payload data
    crc32: bool
        Calculate and append CRC32 to end of packet. Enabled by default.

    Rasises
    -------
    Ax25Error
        On any error

    Returns
    -------
    bytes
        The AX25 packet.
    """

    if len(dest) > AX25_CALLSIGN_LEN:
        raise Ax25Error("dest callsign must be less than 6 chars")
    if dest_ssid < 0 or dest_ssid > 15:
        raise Ax25Error("dest_ssid must be between 0 and 15")
    if len(src) > AX25_CALLSIGN_LEN:
        raise Ax25Error("src callsign must be less than 6 chars")
    if src_ssid < 0 or src_ssid > 15:
        raise Ax25Error("src_ssid must be between 0 and 15")
    if len(payload) > AX25_PAYLOAD_MAX_LEN:
        raise Ax25Error(f"payload must be less than {AX25_PAYLOAD_MAX_LEN} bytes")

    # callsigns must be 6 chars, add trailing spaces as padding
    src += " " * (AX25_CALLSIGN_LEN - len(src))
    dest += " " * (AX25_CALLSIGN_LEN - len(dest))

    # make AX25 packet header
    header = (
        dest.encode()
        + dest_ssid.to_bytes(1, "little")
        + src.encode()
        + src_ssid.to_bytes(1, "little")
        + control.to_bytes(1, "little")
        + pid.to_bytes(1, "little")
    )
    header = (bitstring.BitArray(header) << 1).bytes

    packet = header + payload

    if crc32:
        packet += zlib.crc32(packet, 0).to_bytes(4, "little")

    return packet
