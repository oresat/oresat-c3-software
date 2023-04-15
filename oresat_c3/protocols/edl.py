import binascii
import hashlib
import hmac
from enum import IntEnum, auto

from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLen
from spacepackets.uslp.frame import TransferFrame, TransferFrameDataField, TfdzConstructionRules, \
    UslpProtocolIdentifier, VarFrameProperties, FrameType
from spacepackets.uslp.header import PrimaryHeader, SourceOrDestField, ProtocolCommandFlag, \
    BypassSequenceControlFlag


class EdlCode(IntEnum):
    '''The EDL telecommand codes.'''

    TX_CTRL = 0
    '''
    Enable / Disable Tx.

    Parameters
    ----------
    enable: bool
        True to enable Tx or False to disable Tx

    Returns
    -------
    bool
        Tx status
    '''

    C3_SOFTRESET = auto()
    '''
    Soft reset the C3 (reboot C3 daemon).
    '''

    C3_HARDRESET = auto()
    '''
    Hard reset the C3 (reboot system).
    '''

    C3_FACTORYRESET = auto()
    '''
    Factory reset the C3 (clear FRAM, reset RTC, and reboot system).
    '''

    I2C_RESET = auto()
    '''
    Reset I2C? OPD? TODO

    Returns
    -------
    uint8
        with value of 0
    '''

    CO_NODE_ENABLE = auto()
    '''
    Enable a CANopen node.

    Parameters
    ----------
    node_id: uint8
        Node id of the CANopen node to enable / disable
    enable: bool
        True to enable or False to disable

    Returns
    -------
    uint8
        node status
    '''

    CO_NODE_STATUS = auto()
    '''
    Get the status of a CANopen node.

    Parameters
    ----------
    node_id: uint8
        Node id of node to get the status for

    Return
    ------
    uint8
        node status
    '''

    CO_SDO_WRITE = auto()
    '''
    Send a CANopen SDO write command over CAN bus.

    Parameters
    ----------
    node_id: uint8
        The id of The CANopen node to write to.
    index: uint16
        The OD index to write to.
    subindex: uint8
        The OD subindex to write to.
    size: uint32
        Size of the data buffer.
    buffer: bytes
        Data buffer.

    Returns
    -------
    uint32
        SDO error code (0 is no error).
    '''

    CO_SYNC = auto()
    '''
    Send a CANopen SYNC command on the CAN bus.

    Return
    ------
    bool
        The CANopen SYNC command was sent successfully.
    '''

    OPD_SYSENABLE = auto()
    '''
    Enable the OPD system.

    Parameters
    ----------
    enable: bool
        True to enable or False to disable.

    Return
    ------
    bool
        OPD system status
    '''

    OPD_SCAN = auto()
    '''
    Scan for a node on the OPD.

    Parameters
    ----------
    node_id: int8
        The id of the OPD node to scan for.

    Return
        int8: OPD node status ??? TODO.
    '''

    OPD_ENABLE = auto()
    '''
    Enable / Disable a node on the OPD.

    Parameters
    ----------
    node_id: int8
        The id of the OPD node to enable / disable.
    enable: bool
        True to enable or False to disable.

    Return
        int8: OPD node status ??? TODO.
    '''

    OPD_RESET = auto()
    '''
    Reset a node on the OPD.

    Parameters
    ----------
    node_id: int8
        The id of the OPD node to reset.

    Returns
    -------
    int8
        OPD node status
    '''

    OPD_STATUS = auto()
    '''
    Get the status of a node on the OPD.

    Parameters
    ----------
    node_id: int8
        The id of the OPD node to get the status of.

    Returns
    -------
    int8
        OPD node status.
    '''

    RTC_SET_TIME = auto()
    '''
    Set the RTC time

    Parameters
    ----------
    time: uint32
        The unix time in seconds.

    Return
    ------
    bool
        The RTC time was set successfully.
    '''

    TIME_SYNC = auto()
    '''
    Send OreSat's Time Sync TPDO over the CAN bus.

    Returns
    -------
    bool
        Time sync was sent.
    '''


def crc16_bytes(data: bytes) -> bytes:
    '''Helper function for generating the crc16 of a message as bytes'''
    return binascii.crc_hqx(data, 0).to_bytes(2, 'little')


class EdlError(Exception):
    '''Error with EdlBase'''


class EdlBase:

    SPACECRAFT_ID = 0x4F53  # aka "OS" in ascii

    PRIMARY_HEADER_LEN = 7
    SEQ_NUM_LEN = 4
    DFH_LEN = 1
    HMAC_LEN = 32
    FECF_LEN = 2
    _TC_MIN_LEN = PRIMARY_HEADER_LEN + SEQ_NUM_LEN + DFH_LEN + HMAC_LEN + FECF_LEN

    FRAME_PROPS = VarFrameProperties(
        has_insert_zone=True,
        has_fecf=True,
        truncated_frame_len=0,
        insert_zone_len=SEQ_NUM_LEN,
        fecf_len=FECF_LEN,
    )

    def __init__(self, hmac_key: bytes, sequence_number: int):

        self._hmac_key = b'\x00'
        self.hmac_key = hmac_key
        self._seq_num = sequence_number

    def _gen_hmac(self, message: bytes) -> bytes:

        return hmac.digest(self._hmac_key, message, hashlib.sha3_256)

    def _parse_packet(self, packet: bytes, src_dest: SourceOrDestField) -> bytes:

        if len(packet) < self._TC_MIN_LEN:
            raise EdlError(f'EDL packet too short: {len(packet)}')

        crc16_raw = packet[-self.FECF_LEN:]
        crc16_raw_calc = crc16_bytes(packet[:-self.FECF_LEN])
        if crc16_raw_calc != crc16_raw:
            raise EdlError(f'invalid FECF: {crc16_raw} vs {crc16_raw_calc}')

        try:
            frame = TransferFrame.unpack(packet, FrameType.VARIABLE, self.FRAME_PROPS)
        except UslpInvalidRawPacketOrFrameLen:
            raise EdlError('USLP invalid packet or frame length')

        if frame.insert_zone > self.sequence_number_bytes:
            raise EdlError(f'invalid sequence number: {frame.insert_zone} vs '
                           f'{self.sequence_number_bytes}')

        payload = frame.tfdf.tfdz[:-self.HMAC_LEN]
        hmac_bytes = frame.tfdf.tfdz[-self.HMAC_LEN:]
        hmac_bytes_calc = self._gen_hmac(payload)

        if hmac_bytes != hmac_bytes_calc:
            raise EdlError(f'invalid HMAC {hmac_bytes.hex()} vs {hmac_bytes_calc.hex()}')

        return payload

    def _generate_packet(self, payload: bytes, src_dest: SourceOrDestField) -> bytes:

        # USLP transfer frame total length - 1
        frame_len = len(payload) + self._TC_MIN_LEN - 1

        frame_header = PrimaryHeader(
            scid=self.SPACECRAFT_ID,
            map_id=0,
            vcid=0,
            src_dest=src_dest,
            frame_len=frame_len,
            vcf_count_len=0,
            op_ctrl_flag=False,
            prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
            bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        tfdz = payload + self._gen_hmac(payload)

        tfdf = TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=UslpProtocolIdentifier.MISSION_SPECIFIC_INFO_1_MAPA_SDU,
            tfdz=tfdz,
        )

        frame = TransferFrame(header=frame_header, tfdf=tfdf,
                              insert_zone=self.sequence_number_bytes)
        packet = frame.pack(frame_type=FrameType.VARIABLE)
        packet += crc16_bytes(packet)

        self._seq_num += 1
        self._seq_num %= 0xFF_FF_FF_FF

        return packet

    @property
    def sequence_number(self) -> int:

        return self._seq_num

    @property
    def sequence_number_bytes(self) -> bytes:

        return self._seq_num.to_bytes(self.SEQ_NUM_LEN, 'little')

    @property
    def hmac_key(self) -> bytes:

        return self._hmac_key

    @hmac_key.setter
    def hmac_key(self, value: bytes or bytearray):

        if not isinstance(value, bytes) and not isinstance(value, bytearray):
            raise EdlError('invalid HMAC key data type')

        self._hmac_key = bytes(value)


class EdlServer(EdlBase):

    def parse_request(self, packet: bytes) -> bytes:

        return self._parse_packet(packet, src_dest=SourceOrDestField.SOURCE)

    def generate_response(self, payload: bytes) -> bytes:

        return self._generate_packet(payload, src_dest=SourceOrDestField.DEST)


class EdlClient(EdlBase):

    def generate_request(self, payload: bytes) -> bytes:

        return self._generate_packet(payload, src_dest=SourceOrDestField.SOURCE)

    def parse_response(self, packet: bytes) -> bytes:

        return self._parse_packet(packet, src_dest=SourceOrDestField.DEST)
