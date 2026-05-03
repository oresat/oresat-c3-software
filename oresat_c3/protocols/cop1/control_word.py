import struct
from dataclasses import dataclass


@dataclass
class ControlWord:
    """Communications Link Control Word per CCSDS 232.0-B-4."""

    control_word_type: int = 0  # 1 bit,  always 0 for CLCW
    version_number: int = 0  # 2 bits, always 0b00
    status_field: int = 0  # 3 bits
    cop_in_effect: int = 1  # 2 bits, 01 = COP-1
    vcid: int = 0  # 6 bits
    no_rf_available: bool = False  # flag bit
    no_bit_lock: bool = False  # flag bit
    lockout: bool = False  # flag bit
    wait: bool = False  # flag bit
    retransmit: bool = False  # flag bit
    farm_b_counter: int = 0  # 2 bits
    report_value: int = 0  # 8 bits

    def pack(self) -> bytes:
        word = 0
        word |= (self.control_word_type & 0x1) << 31
        word |= (self.version_number & 0x3) << 29
        word |= (self.status_field & 0x7) << 26
        word |= (self.cop_in_effect & 0x3) << 24
        word |= (self.vcid & 0x3F) << 18
        word |= (int(self.no_rf_available) & 0x1) << 15
        word |= (int(self.no_bit_lock) & 0x1) << 14
        word |= (int(self.lockout) & 0x1) << 13
        word |= (int(self.wait) & 0x1) << 12
        word |= (int(self.retransmit) & 0x1) << 11
        word |= (self.farm_b_counter & 0x3) << 9
        word |= self.report_value & 0xFF
        return struct.pack(">I", word)

    @classmethod
    def unpack(cls, data: bytes) -> "ControlWord":
        if len(data) < 4:
            raise ValueError(f"CLCW requires 4 bytes, got {len(data)}")
        (word,) = struct.unpack(">I", data[:4])
        return cls(
            control_word_type=(word >> 31) & 0x1,
            version_number=(word >> 29) & 0x3,
            status_field=(word >> 26) & 0x7,
            cop_in_effect=(word >> 24) & 0x3,
            vcid=(word >> 18) & 0x3F,
            no_rf_available=bool((word >> 15) & 0x1),
            no_bit_lock=bool((word >> 14) & 0x1),
            lockout=bool((word >> 13) & 0x1),
            wait=bool((word >> 12) & 0x1),
            retransmit=bool((word >> 11) & 0x1),
            farm_b_counter=(word >> 9) & 0x3,
            report_value=word & 0xFF,
        )
