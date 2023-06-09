'''
Anything dealing with packing and unpacking an EDL (Engineering Data Link) packets.
'''

import binascii
import hashlib
import hmac
import struct
from enum import IntEnum, auto
from collections import namedtuple

from spacepackets.uslp.defs import UslpInvalidRawPacketOrFrameLen
from spacepackets.uslp.frame import TransferFrame, TransferFrameDataField, TfdzConstructionRules, \
    UslpProtocolIdentifier, VarFrameProperties, FrameType
from spacepackets.uslp.header import PrimaryHeader, SourceOrDestField, ProtocolCommandFlag, \
    BypassSequenceControlFlag

SRC_DEST_ORESAT = SourceOrDestField.SOURCE
SRC_DEST_UNICLOGS = SourceOrDestField.DEST

EdlCommand = namedtuple(
    'EdlCommand',
    ['req_fmt', 'res_fmt', 'req_func', 'res_func'],
    defaults=(None, None, None, None)
)
'''
Parameters
----------
req_fmt: str
    The struct.unpack() format for request packet.
res_fmt: str
    The struct.pack() format for response packet.
req_func: Callable[[bytes], tuple]
    Optional callback function to use instead of req_fmt for unpacking the request packet.
res_func: Callable[[tuple], bytes]
    Optional callback function to use instead of res_fmt for packing the response packet.
'''


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

    C3_SOFT_RESET = auto()
    '''
    Soft reset the C3 (reboot C3 daemon).
    '''

    C3_HARD_RESET = auto()
    '''
    Hard reset the C3 (reboot system).
    '''

    C3_FACTORY_RESET = auto()
    '''
    Factory reset the C3 (clear FRAM, reset RTC, and reboot system).
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

    Returns
    -------
    uint8
        node status
    '''

    CO_SDO_WRITE = auto()
    '''
    Write a value to a node's OD over the CAN bus using a CANopen SDO message.

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
    Send a CANopen SYNC message on the CAN bus.

    Returns
    -------
    bool
        The CANopen SYNC message was sent successfully.
    '''

    OPD_SYSENABLE = auto()
    '''
    Enable the OPD subsystem.

    Parameters
    ----------
    enable: bool
        True to enable or False to disable.

    Returns
    -------
    bool
        OPD subsystem status.
    '''

    OPD_SCAN = auto()
    '''
    Scan for all nodes on the OPD.

    Returns
    -------
    uint8:
        The number of nodes found.
    '''

    OPD_PROBE = auto()
    '''
    Probe for a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to probe for.

    Returns
    -------
    bool:
        True if the node was found or False if not.
    '''

    OPD_ENABLE = auto()
    '''
    Enable / disable a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to enable / disable.
    enable: bool
        True to enable or False to disable.

    Returns
    -------
    uint8:
        OPD node status. See the OPD page.
    '''

    OPD_RESET = auto()
    '''
    Reset a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to reset.

    Returns
    -------
    uint8:
        OPD node status. See the OPD page.
    '''

    OPD_STATUS = auto()
    '''
    Get the status of a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to get the status of.

    Returns
    -------
    uint8:
        OPD node status. See the OPD page.
    '''

    RTC_SET_TIME = auto()
    '''
    Set the RTC time

    Parameters
    ----------
    time: uint32
        The unix time in seconds.

    Returns
    -------
    bool
        The RTC time was set successfully.
    '''

    TIME_SYNC = auto()
    '''
    C3 will send OreSat's Time Sync TPDO over the CAN bus (all nodes that are powered on and care
    about time will sync to it).

    Returns
    -------
    bool
        Time sync was sent.
    '''


def _edl_res_sdo_write_cb(request_raw: bytes) -> tuple:

    res = struct.unpack('<2BHI', request_raw[:8])
    res += (request_raw[8:])

    return res


EDL_COMMANDS = {
    EdlCode.TX_CTRL: EdlCommand('?', '?'),
    EdlCode.C3_SOFT_RESET: EdlCommand(),
    EdlCode.C3_HARD_RESET: EdlCommand(),
    EdlCode.C3_FACTORY_RESET: EdlCommand(),
    EdlCode.CO_NODE_ENABLE: EdlCommand('B?', 'B'),
    EdlCode.CO_NODE_STATUS: EdlCommand('B', 'B'),
    EdlCode.CO_SDO_WRITE: EdlCommand(None, 'I', _edl_res_sdo_write_cb),
    EdlCode.CO_SYNC: EdlCommand(None, '?'),
    EdlCode.OPD_SYSENABLE: EdlCommand(None, '?'),
    EdlCode.OPD_SCAN: EdlCommand(None, 'B'),
    EdlCode.OPD_PROBE: EdlCommand('B', '?'),
    EdlCode.OPD_ENABLE: EdlCommand('B', 'B'),
    EdlCode.OPD_RESET: EdlCommand('B', 'B'),
    EdlCode.OPD_STATUS: EdlCommand('B', 'B'),
    EdlCode.RTC_SET_TIME: EdlCommand('I', '?'),
}
'''All valid EDL commands lookup table'''


def crc16_bytes(data: bytes) -> bytes:
    '''Helper function for generating the crc16 of a message as bytes'''
    return binascii.crc_hqx(data, 0).to_bytes(2, 'little')


class EdlError(Exception):
    '''Error with EdlBase'''


class EdlRequest:
    '''
    An request payload for an EDL command for the C3 to process.
    '''

    def __init__(self, code: EdlCode, args: tuple):
        '''
        Parameters
        ----------
        code: EdlCode
            The EDL code
        args: tuple
            The arguments for the EDL command
        '''

        if code not in list(EdlCode):
            raise EdlError(f'Invalid EDL code {code}')
        if not isinstance(args, tuple) and args is not None:
            raise EdlError('EdlRequest args must be a tuple or None')

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.args = args

    def pack(self) -> bytes:
        '''
        Pack the EDL C3 command request packet.
        '''

        if self.command.req_fmt is not None:
            raw = struct.pack(self.command.req_fmt, *self.args)
        elif self.command.req_func is not None:
            raw = self.command.res_func(self.args)
        else:
            raw = b''

        return raw

    def unpack(cls, raw: bytes):
        '''
        Unpack the EDL C3 command response packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        '''

        code_int = int.from_bytes(raw[0], 'little')
        code = EdlCode(code_int)
        command = EDL_COMMANDS[code]

        if command.req_fmt is not None:
            args = struct.unpack(command.req_fmt, raw)
        elif command.req_func is not None:
            args = command.req_func(raw)
        else:
            args = None

        return cls.__init__(code, args)


class EdlRespone:
    '''
    An response payload to an EDL command from the C3.
    '''

    def __init__(self, code: EdlCode, values: tuple):
        '''
        Parameters
        ----------
        code: EdlCode
            The EDL code
        values: tuple
            The return values for the response.
        '''

        if code not in list(EdlCode):
            raise EdlError(f'Invalid EDL code {code}')
        if not isinstance(values, tuple) and values is not None:
            raise EdlError('EdlRespone values must be a tuple or None')

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.values = values

    def pack(self) -> bytes:
        '''
        Pack the EDL C3 command response.
        '''

        if self.command.req_fmt is not None:
            raw = struct.pack(self.command.res_fmt, *self.values)
        elif self.command.req_func is not None:
            raw = self.command.res_func(self.values)
        else:
            raw = b''

        return raw

    @classmethod
    def unpack(cls, raw: bytes):
        '''
        Unpack the EDL C3 command response.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        '''

        code_int = int.from_bytes(raw[0], 'little')
        code = EdlCode(code_int)
        command = EDL_COMMANDS[code]

        if command.req_fmt is not None:
            values = struct.unpack(command.res_fmt, raw)
        elif command.req_func is not None:
            values = command.req_func(raw)
        else:
            values = None

        return cls.__init__(code, values)


def gen_hmac(hmac_key, message: bytes) -> bytes:

    return hmac.digest(hmac_key, message, hashlib.sha3_256)


class EdlVcid(IntEnum):
    '''USLP virtual channel IDs for EDL packets'''

    C3_COMMAND = 0
    FILE_TRANSFER = 1


class EdlPacket:
    '''
    An EDL (Engineering Data Link) packet.

    Only packs and unpacks the packet (does not process/run it).
    '''

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

    def __init__(self, payload: EdlRequest or EdlRespone, seq_num: int,
                 src_dest: SourceOrDestField) -> bytes:
        '''
        Parameters
        ----------
        payload: EdlRequest or EdlRespone
            The payload object.
        seq_num: int
            The sequence number for packet.
        src_dest: SourceOrDestFiedld
            Origin of packet, use `SRC_DEST_ORESAT` or `SRC_DEST_UNICLOGS`.
        '''

        if isinstance(payload, EdlRequest) or isinstance(payload, EdlRespone):
            vcid = EdlVcid.C3_COMMAND
        else:
            raise EdlCode(f'unknown payload object: {type(payload)}')

        self.vcid = vcid
        self.src_dest = src_dest
        self.seq_num = seq_num
        self.payload = payload

    def pack(self, hmac_key: bytes) -> bytes:
        '''
        Pack the EDL packet.

        Parameters
        ----------
        hmac_key: bytes
            The HMAC key to use.
        '''

        payload_raw = self.payload.pack()
        tfdz = payload_raw + gen_hmac(hmac_key, payload_raw)

        tfdf = TransferFrameDataField(
            tfdz_cnstr_rules=TfdzConstructionRules.VpNoSegmentation,
            uslp_ident=UslpProtocolIdentifier.MISSION_SPECIFIC_INFO_1_MAPA_SDU,
            tfdz=tfdz,
        )

        # USLP transfer frame total length - 1
        frame_len = len(payload_raw) + self.TC_MIN_LEN - 1

        frame_header = PrimaryHeader(
            scid=self.SPACECRAFT_ID,
            map_id=0,
            vcid=self.vcid,
            src_dest=self.src_dest,
            frame_len=frame_len,
            vcf_count_len=0,
            op_ctrl_flag=False,
            prot_ctrl_cmd_flag=ProtocolCommandFlag.USER_DATA,
            bypass_seq_ctrl_flag=BypassSequenceControlFlag.SEQ_CTRLD_QOS,
        )

        seq_num_bytes = self.seq_num.to_bytes(self.SEQ_NUM_LEN, 'little')
        frame = TransferFrame(header=frame_header, tfdf=tfdf, insert_zone=seq_num_bytes)
        packet = frame.pack(frame_type=FrameType.VARIABLE)
        packet += crc16_bytes(packet)

        return packet

    @classmethod
    def unpack(cls, raw: bytes):
        '''
        Unpack the EDL packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        '''

        if len(raw) < cls._TC_MIN_LEN:
            raise EdlError(f'EDL packet too short: {len(raw)}')

        crc16_raw = raw[-cls.FECF_LEN:]
        crc16_raw_calc = crc16_bytes(raw[:-cls.FECF_LEN])
        if crc16_raw_calc != crc16_raw:
            raise EdlError(f'invalid FECF: {crc16_raw} vs {crc16_raw_calc}')

        try:
            frame = TransferFrame.unpack(raw, FrameType.VARIABLE, cls.FRAME_PROPS)
        except UslpInvalidRawPacketOrFrameLen:
            raise EdlError('USLP invalid packet or frame length')

        payload_raw = frame.tfdf.tfdz[:-cls.HMAC_LEN]
        hmac_bytes = frame.tfdf.tfdz[-cls.HMAC_LEN:]
        hmac_bytes_calc = gen_hmac(payload_raw)

        if hmac_bytes != hmac_bytes_calc:
            raise EdlError(f'invalid HMAC {hmac_bytes.hex()} vs {hmac_bytes_calc.hex()}')

        if frame.header.vcid == EdlVcid.C3_COMMAND:
            if frame.header.src_dest == SRC_DEST_ORESAT:
                payload = EdlRequest.unpack(payload_raw)
            else:
                payload = EdlRespone.unpack(payload_raw)
        else:
            raise EdlCode(f'unknown vcid {frame.header.vcid}')

        seq_num = int.from_bytes(frame.insert_zone, 'little')

        return cls.__init__(payload, seq_num, frame.header.src_dest)
