from dataclasses import dataclass

@dataclass
class Gvcid:
    """Global Virtual Channel Identifier

    CCSDS 732.1-B
    GVCID = TFVN + SCID + VCID

    Parameters
    ----------
    tfvn: int
        Transfer Frame Version Number. Must be 4 bits
    scid: int
        Spacecraft Identifier. Must be 16 bits
    vcid: int
        Virtual Channel Identifier. Must be 6 bits
    """

    tfvn: int  # 4 bits
    scid: int  # 16 bits
    vcid: int  # 6 bits

    def __post_init__(self):
        if not 0 <= self.tfvn <= 0xF:
            raise ValueError(f"TFVN must be 4 bits, got {self.tfvn}")
        if not 0 <= self.scid <= 0xFFFF:
            raise ValueError(f"SCID must be 16 bits, got {self.scid}")
        if not 0 <= self.vcid <= 0x3F:
            raise ValueError(f"VCID must be 6 bits, got {self.vcid}")

    def to_int(self) -> int:
        return (self.tfvn << 22) | (self.scid << 6) | self.vcid

    @classmethod
    def from_int(cls, value: int) -> "Gvcid":
        return cls(
            tfvn=(value >> 22) & 0xF,
            scid=(value >> 6)  & 0xFFFF,
            vcid= value        & 0x3F,
        )