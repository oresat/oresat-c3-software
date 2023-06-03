'''
Abstraction on top the FM24CL64B (F-RAM) driver to define, set, and get data from the F-RAM chip.
'''


import struct
from collections import namedtuple, OrderedDict
from enum import Enum, auto

from ..drivers.fm24cl64b import Fm24cl64b, Fm24cl64bError

FramEntry = namedtuple('FramEntry', ['offset', 'fmt', 'size'])
'''An F-RAM entry in lookup table'''


class FramKey(Enum):
    '''
    All the keys for entries in :py:class:`Fram` class.

    Using an enum helps to reduce errors when compared to using strings.

    Using :py:func:`auto` as the values do not matter at all.
    '''

    C3_STATE = auto()
    LAST_TIME_STAMP = auto()
    ALARM_A = auto()
    ALARM_B = auto()
    WAKEUP = auto()
    LAST_TX_ENABLE = auto()
    LAST_EDL = auto()
    DEPLOYED = auto()
    POWER_CYCLES = auto()
    LBAND_RX_BYTES = auto()
    LBAND_RX_PACKETS = auto()
    VC1_SEQUENCE_COUNT = auto()
    VC1_EXPEDITE_COUNT = auto()
    EDL_SEQUENCE_COUNT = auto()
    EDL_REJECTED_COUNT = auto()
    CRYTO_KEY = auto()


class FramError(Exception):
    '''Error with :py:class:`Fram`'''


class Fram:
    '''
    A dictionary-like class wapper ontop of the :py:class:`Fm24cl64b` class for reading and
    writing values to F-RAM; where the offset and data types are defined in a lookup table.
    '''

    def __init__(self, bus_num: int, addr: int, mock: bool = False):

        self._fm24cl64b = Fm24cl64b(bus_num, addr, mock)

        self._total_bytes = 0
        self._entries = OrderedDict()  # lookup table for entries

        self._init = True

        # add the entries in order to make the lookup table
        # add new entries to the end
        # if a entry's data type or size has change or is no longer used, leave it existing entry,
        # and add a new entry to the end
        self._add_entry(FramKey.C3_STATE, 'B')  # uint8
        self._add_entry(FramKey.LAST_TIME_STAMP, 'Q')  # uint64
        self._add_entry(FramKey.ALARM_A, 'I')  # uint32
        self._add_entry(FramKey.ALARM_B, 'I')
        self._add_entry(FramKey.WAKEUP, 'I')
        self._add_entry(FramKey.LAST_TX_ENABLE, 'I')
        self._add_entry(FramKey.LAST_EDL, 'I')
        self._add_entry(FramKey.DEPLOYED, '?')  # bool
        self._add_entry(FramKey.POWER_CYCLES, 'H')  # uint16
        self._add_entry(FramKey.LBAND_RX_BYTES, 'I')
        self._add_entry(FramKey.LBAND_RX_PACKETS, 'I')
        self._add_entry(FramKey.VC1_SEQUENCE_COUNT, 'Q')
        self._add_entry(FramKey.VC1_EXPEDITE_COUNT, 'Q')
        self._add_entry(FramKey.EDL_SEQUENCE_COUNT, 'I')
        self._add_entry(FramKey.EDL_REJECTED_COUNT, 'I')
        self._add_entry(FramKey.CRYTO_KEY, 128)  # bytes

        self._init = False

    def _add_entry(self, key: str, fmt: [str, int]):
        '''
        Parameters
        -----------
        key: FramKey
            The key
        fmt: [str, int]
            The struct format, see https://docs.python.org/3/library/struct.html.
            For a fixed length bytes buffer, set to number of bytes.
        '''

        if not self._init:
            raise FramError('do not dyanimaic add entries after __init__')
        if key not in list(FramKey):
            raise FramError(f'{key} is not a valid key')
        if not isinstance(fmt, str) and not isinstance(fmt, int):
            raise FramError('fmt must a struct format string or the number of bytes')

        if isinstance(fmt, int):
            size = fmt
            fmt = None
        else:
            size = struct.calcsize(fmt)

        self._entries[key] = FramEntry(self._total_bytes, fmt, size)
        self._total_bytes += size

    def __len__(self) -> int:

        return len(list(FramKey))

    def __getitem__(self, key: FramKey) -> [bytes, bool, int, float]:

        if key not in list(FramKey):
            raise FramError(f'{key} is not a valid key')

        entry = self._entries[key]

        try:
            raw = self._fm24cl64b.read(entry.offset, entry.size)
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM read failed with {e}')

        if entry.fmt is None:
            value = raw
        else:
            try:
                value = struct.unpack(entry.fmt, raw)[0]
            except struct.error as e:
                raise FramError(f'F-RAM unpack failed with {e}')

        return value

    def __setitem__(self, key: FramKey, value: [bytes, bool, int, float]):

        if key not in list(FramKey):
            raise FramError(f'{key} is not a valid key')

        entry = self._entries[key]

        if entry.fmt == '?' and not isinstance(value, bool):  # struct still packs non-bool as bool
            raise FramError(f'{key.name} cannot write a non-bool value to a bool entry')

        if entry.fmt is None:
            if not isinstance(value, bytes) or isinstance(value, bytearray):
                raise FramError(f'{key.name} value not a bytes or bytearray; is a {type(value)}')
            raw = value
        else:
            try:
                raw = struct.pack(entry.fmt, value)
            except struct.error as e:
                raise FramError(f'F-RAM pack failed with {e}')

        if entry.fmt is None and len(raw) != entry.size:
            raise FramError(f'F-RAM entry {key.name} must be {entry.size} bytes')

        try:
            self._fm24cl64b.write(entry.offset, raw)
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM write failed with {e}')

    def get_all(self) -> dict:
        '''
        Get all values at once.

        Returns
        -------
        dict
            All the value, use FramKey for the keys
        '''

        try:
            raw = self._fm24cl64b.read(0, self._total_bytes)
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM get_all failed with {e}')

        data = {}

        for key in list(FramKey):
            entry = self._entries[key]
            raw_value = raw[entry.offset: entry.offset + entry.size]

            if entry.fmt is None:
                value = raw_value
            else:
                try:
                    value = struct.unpack(entry.fmt, raw_value)[0]
                except ValueError as e:
                    raise FramError(f'F-RAM unpack failed with {e}')

            data[key] = value

        return data

    def clear(self):
        '''Clear the F-RAM'''

        try:
            self._fm24cl64b.write(0, self._total_bytes, bytes([0] * self._total_bytes))
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM clear failed with {e}')
