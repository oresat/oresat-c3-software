''''
FM24CL64B F-RAM driver

The FM24CL64B is a 64-Kbit F-RAM (ferroelectric random access memory) with an I2C interface.
'''

from smbus2 import SMBus, i2c_msg


class Fm24cl64bError(Exception):
    '''Error with `Fm24cl64b`'''


class Fm24cl64b:
    ''''FM24CL64B F-RAM driver'''

    ADDR_MIN = 0x50
    ADDR_MAX = 0x5F
    ADDRESSES = list(range(ADDR_MIN, ADDR_MAX + 2, 2))

    def __init__(self, bus_num: int, addr: int, mock: bool = False):
        '''
        Parameters
        ----------
        bus: int
            The I2C bus.
        addr: int
            The I2C address, must be between `ADDR_MIN` and `ADDR_MAX`.
        mock: bool:
            Mock the FM24CL64B.
        '''

        if addr < self.ADDR_MIN or addr > self.ADDR_MAX:
            raise Fm24cl64bError(f'arg addr 0x{addr:X} is not between 0x{self.ADDR_MIN:X} '
                                 f'and 0x{self.ADDR_MAX:X}')

        self._bus_num = bus_num
        self._addr = addr
        self._mock = mock
        if mock:
            self._mock_data = bytearray([0] * 8000)

    def read(self, offset: int, size: int) -> bytes:
        '''
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
        '''

        address = offset.to_bytes(2, 'little')

        if self._mock:
            result = self._mock_data[offset: offset + size]
        else:
            write = i2c_msg.write(self._addr, address)
            read = i2c_msg.read(self._addr, size)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write, read)
            except OSError:
                raise Fm24cl64bError(f'FM24CL64B at address 0x{self._addr:02X} does not exist')

            result = list(read)

        return bytes(result)

    def write(self, offset: int, data: bytes):
        '''
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
        '''

        if not isinstance(data, bytes) and not isinstance(data, bytearray):
            raise Fm24cl64bError(f'write data must be a bytes or bytearray type not {type(data)}')

        size = len(data)
        address = offset.to_bytes(2, 'little')

        if self._mock:
            self._mock_data[offset: offset + size] = data
        else:
            write = i2c_msg.write(self._addr, address + data)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write)
            except OSError:
                raise Fm24cl64bError(f'FM24CL64B at address 0x{self._addr:02X} does not exist')
