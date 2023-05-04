'''
Abstraction on top the FM24CL64B (F-RAM) driver to define, set, and get data from the F-RAM chip.
'''


import struct
from collections import namedtuple, OrderedDict
from enum import Enum, auto

from ..drivers.fm24cl64b import Fm24cl64b, Fm24cl64bError

FramEntry = namedtuple('FramEntry', ['offset', 'fmt', 'size'])
'''An entry in lookup table'''


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

        # add the entries in order to make the lookup table
        # add new enties to the end
        # if a entry's data type or size has change or is no longer used, leave it existing entry,
        # and add a new entry to the end
        self._add_entry(FramKey.C3_STATE, 'I', 4)  # uint32
        self._add_entry(FramKey.LAST_TIME_STAMP, 'Q', 8)  # uint64
        self._add_entry(FramKey.ALARM_A, 'I', 4)
        self._add_entry(FramKey.ALARM_B, 'I', 4)
        self._add_entry(FramKey.WAKEUP, 'I', 4)
        self._add_entry(FramKey.LAST_TX_ENABLE, 'I', 4)
        self._add_entry(FramKey.LAST_EDL, 'I', 4)
        self._add_entry(FramKey.DEPLOYED, '?', 1)  # bool
        self._add_entry(FramKey.POWER_CYCLES, 'H', 2)  # uint16
        self._add_entry(FramKey.LBAND_RX_BYTES, 'I', 4)
        self._add_entry(FramKey.LBAND_RX_PACKETS, 'I', 4)
        self._add_entry(FramKey.VC1_SEQUENCE_COUNT, 'Q', 8)
        self._add_entry(FramKey.VC1_EXPEDITE_COUNT, 'Q', 8)
        self._add_entry(FramKey.EDL_SEQUENCE_COUNT, 'I', 4)
        self._add_entry(FramKey.EDL_REJECTED_COUNT, 'I', 4)
        self._add_entry(FramKey.CRYTO_KEY, None, 128)  # bytes

    def _add_entry(self, key: str, fmt: str, size: int):
        '''
        Parameters
        -----------
        key: FramKey
            The key
        fmt: str
            The struct format, see https://docs.python.org/3/library/struct.html.
            Set to None, if data type is bytes, for a fixed length buffer.
        size: int
            Size of the data type.
        '''

        if size < 1:
            raise FramError('Size must be set to a number greater than 1')

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

        try:
            value = struct.unpack(entry.fmt, raw)[0]
        except ValueError as e:
            raise FramError(f'F-RAM unpack failed with {e}')

        return value

    def __setitem__(self, key: FramKey, value: [bytes, bool, int, float]):

        if key not in list(FramKey):
            raise FramError(f'{key} is not a valid key')

        entry = self._entries[key]

        if entry.fmt is None and len(value) != entry.size:
            raise FramError(f'F-RAM entry {key.name} must be {entry.size} bytes')

        try:
            raw = struct.pack(entry.fmt, value)
        except ValueError as e:
            raise FramError(f'F-RAM pack failed with {e}')

        try:
            self._fm24cl64b.write(entry.offset, raw)
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM write failed with {e}')

    def clear(self):
        '''Clear the F-RAM'''

        try:
            self._fm24cl64b.write(0, self._total_bytes, bytes([0] * self._total_bytes))
        except Fm24cl64bError as e:
            raise FramError(f'F-RAM clear failed with {e}')
