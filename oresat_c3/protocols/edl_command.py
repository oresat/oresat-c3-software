'''
Anything dealing with packing and unpacking EDL (Engineering Data Link) packets.
'''

import struct
from enum import IntEnum, auto
from collections import namedtuple

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


class EdlCommandPacketError(Exception):
    '''Error with EdlCommandRequest or EdlCommandResponse'''


class EdlCommandCode(IntEnum):
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
    EdlCommandCode.TX_CTRL: EdlCommand('?', '?'),
    EdlCommandCode.C3_SOFT_RESET: EdlCommand(),
    EdlCommandCode.C3_HARD_RESET: EdlCommand(),
    EdlCommandCode.C3_FACTORY_RESET: EdlCommand(),
    EdlCommandCode.CO_NODE_ENABLE: EdlCommand('B?', 'B'),
    EdlCommandCode.CO_NODE_STATUS: EdlCommand('B', 'B'),
    EdlCommandCode.CO_SDO_WRITE: EdlCommand(None, 'I', _edl_res_sdo_write_cb),
    EdlCommandCode.CO_SYNC: EdlCommand(None, '?'),
    EdlCommandCode.OPD_SYSENABLE: EdlCommand(None, '?'),
    EdlCommandCode.OPD_SCAN: EdlCommand(None, 'B'),
    EdlCommandCode.OPD_PROBE: EdlCommand('B', '?'),
    EdlCommandCode.OPD_ENABLE: EdlCommand('B', 'B'),
    EdlCommandCode.OPD_RESET: EdlCommand('B', 'B'),
    EdlCommandCode.OPD_STATUS: EdlCommand('B', 'B'),
    EdlCommandCode.RTC_SET_TIME: EdlCommand('I', '?'),
}
'''All valid EDL commands lookup table'''


class EdlCommandError(Exception):
    '''Error with EdlBase'''


class EdlCommandRequest:
    '''
    An request payload for an EDL command for the C3 to process.
    '''

    def __init__(self, code: EdlCommandCode, args: tuple):
        '''
        Parameters
        ----------
        code: EdlCommandCode
            The EDL code
        args: tuple
            The arguments for the EDL command
        '''

        if code not in list(EdlCommandCode):
            raise EdlCommandError(f'Invalid EDL code {code}')
        if not isinstance(args, tuple) and args is not None:
            raise EdlCommandError('EdlCommandRequest args must be a tuple or None')

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.args = args

    def __eq__(self, other) -> bool:

        if not isinstance(other, EdlCommandRequest):
            return False
        return self.code == other.code and self.args == other.args

    def __str__(self) -> str:

        return f'{self.code} {self.args}'

    def pack(self) -> bytes:
        '''
        Pack the EDL C3 command request packet.
        '''

        raw = self.code.value.to_bytes(1, 'little')

        if self.command.req_fmt is not None:
            raw += struct.pack(self.command.req_fmt, *self.args)
        elif self.command.req_func is not None:
            raw += self.command.res_func(self.args)

        return raw

    @classmethod
    def unpack(cls, raw: bytes):
        '''
        Unpack the EDL C3 command response packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        '''

        code = EdlCommandCode(raw[0])
        command = EDL_COMMANDS[code]

        if command.req_fmt is not None:
            args = struct.unpack(command.req_fmt, raw[1:])
        elif command.req_func is not None:
            args = command.req_func(raw[1:])
        else:
            args = None

        return EdlCommandRequest(code, args)


class EdlCommandResponse:
    '''
    An response payload to an EDL command from the C3.
    '''

    def __init__(self, code: EdlCommandCode, values: tuple):
        '''
        Parameters
        ----------
        code: EdlCommandCode
            The EDL code
        values: tuple
            The return values for the response.
        '''

        if code not in list(EdlCommandCode):
            raise EdlCommandError(f'Invalid EDL code {code}')
        if not isinstance(values, tuple) and values is not None:
            raise EdlCommandError('EdlCommandResponse values must be a tuple or None')

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.values = values

    def __eq__(self, other) -> bool:

        if not isinstance(other, EdlCommandResponse):
            return False
        return self.code == other.code and self.values == other.values

    def pack(self) -> bytes:
        '''
        Pack the EDL C3 command response.
        '''

        raw = self.code.value.to_bytes(1, 'little')

        if self.command.req_fmt is not None:
            raw += struct.pack(self.command.res_fmt, *self.values)
        elif self.command.req_func is not None:
            raw += self.command.res_func(self.values)

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

        code = EdlCommandCode(raw[0])
        command = EDL_COMMANDS[code]

        if command.req_fmt is not None:
            values = struct.unpack(command.res_fmt, raw[1:])
        elif command.req_func is not None:
            values = command.req_func(raw[1:])
        else:
            values = None

        return EdlCommandResponse(code, values)
