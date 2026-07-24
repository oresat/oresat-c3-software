"""
Anything dealing with packing and unpacking EDL (Engineering Data Link) C3 command packets.

These package are defined as 1 octet for code and X octets for the data.

The EDL code is used to identify the message the rest of message is for argument for
request, and values for responses.
"""

import struct
from collections import namedtuple
from enum import IntEnum

EdlCommand = namedtuple(
    "EdlCommand",
    ["req_fmt", "res_fmt", "req_pack_func", "req_unpack_func", "res_pack_func", "res_unpack_func"],
    defaults=(None, None, None, None, None, None),
)
"""
Parameters
----------
req_fmt: str
    The struct.unpack() format for request packet.
res_fmt: str
    The struct.pack() format for response packet.
req_pack_func: Callable[[tuple], bytes]
    Optional callback function to use instead of req_fmt for packing the request packet.
req_unpack_func: Callable[[bytes], tuple]
    Optional callback function to use instead of req_fmt for unpacking the request packet.
res_pack_func: Callable[[tuple], bytes]
    Optional callback function to use instead of res_fmt for packing the response packet.
res_unpack_func: Callable[[bytes], tuple]
    Optional callback function to use instead of res_fmt for unpacking the response packet.
"""


class EdlCommandPacketError(Exception):
    """Error with EdlCommandRequest or EdlCommandResponse"""


class EdlCommandCode(IntEnum):
    """The EDL telecommand codes."""

    TX_CTRL = 0
    """
    Enable / Disable Tx.

    Parameters
    ----------
    enable: bool
        True to enable Tx or False to disable Tx

    Returns
    -------
    bool
        Tx status
    """

    C3_SOFT_RESET = 1
    """
    Soft reset the C3 (reboot C3 daemon).
    """

    C3_HARD_RESET = 2
    """
    Hard reset the C3 (reboot system).
    """

    C3_FACTORY_RESET = 3
    """
    Factory reset the C3 (clear FRAM, reset RTC, and reboot system).
    """

    CO_NODE_ENABLE = 4
    """
    Vestigial command to turn on CANopen in a node. CANopen is always on, so this has no use.
    """

    CO_NODE_STATUS = 5
    """
    Get the status of a CANopen node.

    Parameters
    ----------
    node_id: uint8
        Node id of node to get the status for

    Returns
    -------
    uint8
        node status
    """

    CO_SDO_WRITE = 6
    """
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
    """

    CO_SYNC = 7
    """
    Send a CANopen SYNC message on the CAN bus.

    Returns
    -------
    bool
        The CANopen SYNC message was sent successfully.
    """

    OPD_SYSENABLE = 8
    """
    Enable the OPD subsystem.

    Parameters
    ----------
    enable: bool
        True to enable or False to disable.

    Returns
    -------
    bool
        OPD subsystem status.
    """

    OPD_SCAN = 9
    """
    Scan for all nodes on the OPD.

    Returns
    -------
    uint8:
        The number of nodes found.
    """

    OPD_PROBE = 10
    """
    Probe for a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to probe for.

    Returns
    -------
    bool:
        True if the node was found or False if not.
    """

    OPD_ENABLE = 11
    """
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
    """

    OPD_RESET = 12
    """
    Reset a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to reset.

    Returns
    -------
    uint8:
        OPD node status. See the OPD page.
    """

    OPD_STATUS = 13
    """
    Get the status of a node on the OPD.

    Parameters
    ----------
    node_id: uint8
        The id of the OPD node to get the status of.

    Returns
    -------
    uint8:
        OPD node status. See the OPD page.
    """

    RTC_SET_TIME = 14
    """
    Set the RTC time

    Parameters
    ----------
    time: uint32
        The Unix time in seconds.

    Returns
    -------
    bool
        The RTC time was set successfully.
    """

    TIME_SYNC = 15
    """
    C3 will send OreSat's Time Sync TPDO over the CAN bus (all nodes that are powered on and care
    about time will sync to it).

    Returns
    -------
    bool
        Time sync was sent.
    """

    BEACON_PING = 16
    """
    C3 will response with a beacon regardless of tx state.
    """

    PING = 17
    """
    A basic ping to the C3.

    Parameters
    ----------
    value: uint32
        A value to return.

    Returns
    -------
    uint32:
        The parameter value.
    """

    RX_TEST = 18
    """
    Empty command for C3 Rx testing.
    """

    CO_SDO_READ = 19
    """
    Read a value from a node's OD over the CAN bus using a CANopen SDO message.

    Parameters
    ----------
    node_id: uint8
        The id of The CANopen node to write to.
    index: uint16
        The OD index to write to.
    subindex: uint8
        The OD subindex to write to.

    Returns
    -------
    uint8
        The id of The CANopen node read.
    uint16
        The OD index read.
    uint8
        The OD subindex read.
    uint32
        SDO error code (0 is no error).
    uint32
        Size of the data buffer.
    bytes
        Data buffer.
    """

    CO_NODE_FLASH = 20
    """
    Flash a Zephyr/mcuboot image to a node using CANopen block or segmented download.

    Parameters
    ----------
    node_id: uint8
        The id of the CANopen node to write to.
    filename: str
        The name of the file cached on the C3 to flash.
    throttle_delay: float, optional
        Delay between packets (default: 0.0).
    block_transfer: bool, optional
        True for block download, False for segmented (default: True).
    request_crc: bool, optional
        True to request a CRC check of the block download payload (default: True).
    confirm_image: bool, optional
        True to issue a command to confirm the zephyr image on next boot (default: False).

    Returns
    -------
    bool
        True if the flash command was accepted into the queue.
    """


def _edl_req_sdo_write_pack_cb(values: tuple) -> bytes:
    req = struct.pack("<BHBI", *values[:4])
    return req + values[4]


def _edl_req_sdo_write_unpack_cb(raw: bytes) -> tuple:
    fmt = "<BHBI"
    size = struct.calcsize(fmt)
    values = struct.unpack(fmt, raw[:size])
    return (*values, raw[size:])


def _edl_res_sdo_read_pack_cb(values: tuple) -> bytes:
    res = struct.pack("<BHB2I", *values[:5])
    res += values[5]
    return res


def _edl_res_sdo_read_unpack_cb(raw: bytes) -> tuple:
    fmt = "<BHB2I"
    size = struct.calcsize(fmt)
    res = struct.unpack(fmt, raw[:size])
    res += (raw[size:],)
    return res


def _edl_req_node_flash_pack_cb(values: tuple) -> bytes:
    node_id = values[0]
    filename = values[1]
    throttle_delay = values[2] if len(values) > 2 else 0.0
    block_transfer = values[3] if len(values) > 3 else True
    request_crc = values[4] if len(values) > 4 else True
    confirm_image = values[5] if len(values) > 5 else False
    req = struct.pack("<Bf???", node_id, throttle_delay, block_transfer, request_crc, confirm_image)
    return req + filename.encode("utf-8")


def _edl_req_node_flash_unpack_cb(raw: bytes) -> tuple:
    fmt = "<Bf???"
    size = struct.calcsize(fmt)
    node_id, throttle_delay, block_transfer, request_crc, confirm_image = struct.unpack(
        fmt, raw[:size]
    )
    filename = raw[size:].decode("utf-8").rstrip("\x00")
    return (node_id, filename, throttle_delay, block_transfer, request_crc, confirm_image)


EDL_COMMANDS = {
    EdlCommandCode.TX_CTRL: EdlCommand("?", "?"),
    EdlCommandCode.C3_SOFT_RESET: EdlCommand(),
    EdlCommandCode.C3_HARD_RESET: EdlCommand(),
    EdlCommandCode.C3_FACTORY_RESET: EdlCommand(),
    EdlCommandCode.CO_NODE_ENABLE: EdlCommand(),
    EdlCommandCode.CO_NODE_STATUS: EdlCommand("B", "B"),
    EdlCommandCode.CO_SDO_WRITE: EdlCommand(
        None, "I", _edl_req_sdo_write_pack_cb, _edl_req_sdo_write_unpack_cb
    ),
    EdlCommandCode.CO_SYNC: EdlCommand(None, "?"),
    EdlCommandCode.OPD_SYSENABLE: EdlCommand("?", "?"),
    EdlCommandCode.OPD_SCAN: EdlCommand(None, "B"),
    EdlCommandCode.OPD_PROBE: EdlCommand("B", "?"),
    EdlCommandCode.OPD_ENABLE: EdlCommand("B?", "B"),
    EdlCommandCode.OPD_RESET: EdlCommand("B", "B"),
    EdlCommandCode.OPD_STATUS: EdlCommand("B", "B"),
    EdlCommandCode.RTC_SET_TIME: EdlCommand("I", "?"),
    EdlCommandCode.TIME_SYNC: EdlCommand(None, "?"),
    EdlCommandCode.BEACON_PING: EdlCommand(),
    EdlCommandCode.PING: EdlCommand("I", "I"),
    EdlCommandCode.RX_TEST: EdlCommand(),
    EdlCommandCode.CO_SDO_READ: EdlCommand(
        "BHB",
        None,
        None,
        None,
        _edl_res_sdo_read_pack_cb,
        _edl_res_sdo_read_unpack_cb,
    ),
    EdlCommandCode.CO_NODE_FLASH: EdlCommand(
        None, "?", _edl_req_node_flash_pack_cb, _edl_req_node_flash_unpack_cb
    ),
}
"""All valid EDL commands lookup table"""


class EdlCommandError(Exception):
    """Error with EdlBase"""


class EdlCommandRequest:
    """
    An request payload for an EDL command for the C3 to process.
    """

    def __init__(self, code: EdlCommandCode, args: tuple):
        """
        Parameters
        ----------
        code: EdlCommandCode
            The EDL code
        args: tuple
            The arguments for the EDL command
        """

        if code not in list(EdlCommandCode):
            raise EdlCommandError(f"Invalid EDL code {code}")
        if not isinstance(args, tuple) and args is not None:
            raise EdlCommandError("EdlCommandRequest args must be a tuple or None")

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.args = args

    def __eq__(self, other) -> bool:
        if not isinstance(other, EdlCommandRequest):
            return False
        return self.code == other.code and self.args == other.args

    def __str__(self) -> str:
        return f"{self.code} {self.args}"

    def pack(self) -> bytes:
        """
        Pack the EDL C3 command request packet.
        """

        raw = self.code.value.to_bytes(1, "little")

        if self.command.req_fmt is not None:
            raw += struct.pack("=" + self.command.req_fmt, *self.args)
        elif self.command.req_pack_func is not None:
            raw += self.command.req_pack_func(self.args)

        return raw

    @classmethod
    def unpack(cls, raw: bytes):
        """
        Unpack the EDL C3 command response packet.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        """

        code = EdlCommandCode(raw[0])
        command = EDL_COMMANDS[code]

        if command.req_fmt is not None:
            args = struct.unpack("=" + command.req_fmt, raw[1:])
        elif command.req_unpack_func is not None:
            args = command.req_unpack_func(raw[1:])
        else:
            args = ()

        return EdlCommandRequest(code, args)


class EdlCommandResponse:
    """
    An response payload to an EDL command from the C3.
    """

    def __init__(self, code: EdlCommandCode, values: tuple):
        """
        Parameters
        ----------
        code: EdlCommandCode
            The EDL code
        values: tuple
            The return values for the response.
        """

        if code not in list(EdlCommandCode):
            raise EdlCommandError(f"Invalid EDL code {code}")
        if not isinstance(values, tuple) and values is not None:
            raise EdlCommandError("EdlCommandResponse values must be a tuple or None")

        self.code = code
        self.command = EDL_COMMANDS[code]
        self.values = values

    def __eq__(self, other) -> bool:
        if not isinstance(other, EdlCommandResponse):
            return False
        return self.code == other.code and self.values == other.values

    def pack(self) -> bytes:
        """
        Pack the EDL C3 command response.
        """

        raw = self.code.value.to_bytes(1, "little")

        if self.command.res_fmt is not None:
            raw += struct.pack("=" + self.command.res_fmt, *self.values)
        elif self.command.res_pack_func is not None:
            raw += self.command.res_pack_func(self.values)

        return raw

    @classmethod
    def unpack(cls, raw: bytes):
        """
        Unpack the EDL C3 command response.

        Parameters
        ----------
        raw: bytes
            The raw data to unpack.
        """

        code = EdlCommandCode(raw[0])
        command = EDL_COMMANDS[code]

        if command.res_fmt is not None:
            values = struct.unpack("=" + command.res_fmt, raw[1:])
        elif command.res_unpack_func is not None:
            values = command.res_unpack_func(raw[1:])
        else:
            values = ()

        return EdlCommandResponse(code, values)
