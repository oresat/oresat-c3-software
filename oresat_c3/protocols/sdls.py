import hashlib
import hmac

from olaf import logger

from spacepackets.uslp import (
    PrimaryHeader,
)
import spacepackets.uslp.frame

HMAC_LEN = 32
SPI_LEN = 2
SEQ_NUM_LEN = 4

SPI_LIST = [1, 1, 0] # spi definition.
# There should be some VC parameters class that COP-1 and SDLS reference when determining how to handle VCs.

def gen_hmac(hmac_key: bytes, message: bytes) -> bytes:
    """Helper function to generate HMAC value from HMAC key and the message."""

    return hmac.digest(hmac_key, message, hashlib.sha3_256)

def get_sdls_len(vcid: int) -> int:
    """Get the length of the header and trailer for the SPI associated with the given Virtual Channel.

    Parameters
    ----------
    vcid
        The Virtual Channel Identifier to retrieve the SPI from.

    Returns
    -------
    int
        The length of the sdls header and trailer.
    """
    
    if len(SPI_LIST) <= vcid:
        raise ValueError(f"VCID {vcid} does not have corresponding SPI.")

    spi = SPI_LIST[vcid]
    
    if spi == 1:
        return HMAC_LEN + SPI_LEN + SEQ_NUM_LEN
    elif spi == 0:
        return 0;
    raise ValueError(f"VCID has invalid SPI: {spi}")


def get_sdls_header_len(vcid: int) -> int:
    """Get the length of the header for the SPI associated with the given Virtual Channel.

    Parameters
    ----------
    vcid
        The Virtual Channel Identifier to retrieve the SPI from.

    Returns
    -------
    int
        The length of the sdls headre.
    """
    
    if len(SPI_LIST) <= vcid:
        raise ValueError(f"VCID {vcid} does not have corresponding SPI.")

    spi = SPI_LIST[vcid]
    
    if spi == 1:
        return SPI_LEN + SEQ_NUM_LEN
    elif spi == 0:
        return 0;
    raise ValueError(f"VCID has invalid SPI: {spi}")


def apply_sdls(header: PrimaryHeader, seq_num: int, tfdf: TransferFrameDataField, hmac_key: bytes) -> bytes:
    """Apply the HMAC to the data zone (out of spec but no other choice) and return the header to be put in the insert zone (see previous note.)

    Parameters
    ----------
    header
        The primary header of the frame
    tfdf
        The contents of the transfer frame. As the spacepackets protocol does not support sdls, the MAC will be inserted into the 
        data zone, despite spec stating that this is not the case.

    Returns
    -------
    bytes
        The sdls_header to be put in the insert zone.
    """

    if len(SPI_LIST) <= header.vcid:
        raise ValueError(f"VCID {header.vcid} does not have corresponding SPI.")

    spi = SPI_LIST[header.vcid]
    
    if spi == 1:
        sdls_header = bytearray(b"\x00\x01") + seq_num.to_bytes(SEQ_NUM_LEN, "little")

        authenticated_data = header.pack() + sdls_header + tfdf.pack()

        header_mask = bytearray(b"\x00\x00\x07\xfe\x00\x00\x00")
        header_mask += bytearray(bytes(header.vcf_count_len))

        print(header_mask.hex())

        for i in range(len(header_mask)):
            authenticated_data[i] = authenticated_data[i] & header_mask[i]

        hmac_val = gen_hmac(hmac_key, authenticated_data)
        tfdf.tfdz = tfdf.tfdz + hmac_val

        return sdls_header

    elif spi == 0:
        return bytes(b'')

    raise ValueError(f"VCID has invalid SPI: {spi}")


def verify_sdls(frame: TransferFrame, hmac_key: bytes) -> int:
    """Check that the HMAC is good, then return the sequence number. Sequence number handling should be handled here, but I do not
    have time to disentangle it now. TODO: fix.

    Parameters
    ----------
    frame
        The transfer frame as a TransferFrame object
    hmac_key
        The contents of the transfer frame. As the spacepackets protocol does not support sdls, the MAC will be inserted into the 
        data zone, despite spec stating that this is not the case.

    Returns
    -------
    int
        The sequence number that is handled not here.
    """

    if len(SPI_LIST) <= frame.header.vcid:
        raise ValueError(f"VCID {frame.header.vcid} does not have corresponding SPI.")

    spi = SPI_LIST[frame.header.vcid]
    
    if spi == 1:
        sdls_header = frame.insert_zone
        payload = frame.tfdf.pack()[:-HMAC_LEN]
        authenticated_data = frame.header.pack() + sdls_header + payload

        header_mask = bytearray(b"\x00\x00\x07\xfe\x00\x00\x00")
        header_mask += bytearray(bytes(frame.header.vcf_count_len))
        for i in range(frame.header.vcf_count):
            header_mask += 0x00
        for i in range(len(header_mask)):
            authenticated_data[i] = authenticated_data[i] & header_mask[i]

        hmac_expected = gen_hmac(hmac_key, authenticated_data)
        hmac_actual = frame.tfdf.tfdz[-HMAC_LEN:]

        if hmac_expected != hmac_actual:
            raise EdlPacketError(f"Frame with invalid HMAC received expected: {hmac_expected}, Actual: {hmac_actual}")

        sequence_number = int.from_bytes(sdls_header[:-SEQ_NUM_LEN], byteorder="little")
        return sequence_number

    elif spi == 0:
        return 0

    raise ValueError(f"VCID has invalid SPI: {spi}")