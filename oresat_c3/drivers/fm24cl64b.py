"""'
FM24CL64B F-RAM driver

The FM24CL64B is a 64-Kbit F-RAM (ferroelectric random access memory) with an I2C interface.
"""

import os

from smbus2 import SMBus, i2c_msg


class Fm24cl64bError(Exception):
    """Error with `Fm24cl64b`"""


class Fm24cl64b:
    """'FM24CL64B F-RAM driver"""

    ADDR_MIN = 0x50
    ADDR_MAX = 0x5F
    ADDRESSES = list(range(ADDR_MIN, ADDR_MAX + 1))

    SIZE = 8192  # size of F-RAM in bytes

    MOCK_FILE = "/tmp/FM24CL64B.bin"

    def __init__(self, bus_num: int, addr: int, mock: bool = False):
        """
        Parameters
        ----------
        bus: int
            The I2C bus.
        addr: int
            The I2C address, must be between `ADDR_MIN` and `ADDR_MAX`.
        mock: bool:
            Mock the FM24CL64B.
        """

        if addr not in self.ADDRESSES:
            raise Fm24cl64bError(
                f"arg addr 0x{addr:X} is not between 0x{self.ADDR_MIN:X} "
                f"and 0x{self.ADDR_MAX:X}"
            )

        self._bus_num = bus_num
        self._addr = addr
        self._mock = mock
        if mock and not os.path.isfile(self.MOCK_FILE):
            with open(self.MOCK_FILE, "wb") as f:
                f.write(bytearray([0] * self.SIZE))

    def read(self, offset: int, size: int) -> bytes:
        """
        Read a bytes from F-RAM.

        Raises
        ------
        Fm24cl64bError
            The read failed.

        Parameters
        -----------
        offset: int
            The offset from the start of F-RAM to read at.
        size: int
            The number of bytes to read.

        Returns
        -------
        bytes
            The requested bytes.
        """

        if size < 1:
            raise Fm24cl64bError("read size must be greater than 1")
        if offset < 0 or offset > self.SIZE:
            raise Fm24cl64bError(f"read offset must be greater than 0 and less than {self.SIZE}")
        if offset + size > self.SIZE:
            # this actually valid as the device will wrap around, this just simplifies things
            raise Fm24cl64bError(f"read offset and size are greater than {self.SIZE}")

        address = offset.to_bytes(2, "big")

        if self._mock:
            with open(self.MOCK_FILE, "rb") as f:
                data = bytearray(f.read())
            result = data[offset : offset + size]
        else:
            write = i2c_msg.write(self._addr, address)
            read = i2c_msg.read(self._addr, size)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write, read)
            except OSError:
                raise Fm24cl64bError(f"FM24CL64B at address 0x{self._addr:02X} does not exist")

            result = list(read)  # type: ignore

        return bytes(result)

    def write(self, offset: int, data: bytes):
        """
        Write bytes to F-RAM.

        Raises
        ------
        Fm24cl64bError
            The write failed.

        Parameters
        -----------
        offset: int
            The offset from the start of F-RAM to write to.
        data: bytes
            The data to write.
        """

        if not isinstance(data, bytes) and not isinstance(data, bytearray):
            raise Fm24cl64bError(f"write data must be a bytes or bytearray type not {type(data)}")

        if offset < 0 or offset > self.SIZE:
            raise Fm24cl64bError(f"write offset must be greater than 0 and less than {self.SIZE}")
        if offset + len(data) > self.SIZE:
            raise Fm24cl64bError(f"write offset and data length are greater than {self.SIZE}")
        if len(data) == 0:
            raise Fm24cl64bError("no data to write")

        size = len(data)
        address = offset.to_bytes(2, "big")

        if self._mock:
            with open(self.MOCK_FILE, "rb") as f:
                tmp = bytearray(f.read())
            tmp[offset : offset + size] = data
            with open(self.MOCK_FILE, "wb") as f:
                f.write(tmp)
        else:
            write = i2c_msg.write(self._addr, address + data)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write)
            except OSError:
                raise Fm24cl64bError(f"FM24CL64B at address 0x{self._addr:02X} does not exist")

    def clear(self):
        """Clear the bytes in the F-RAM."""

        self.write(0, b"\x00" * (self.SIZE // 2))
