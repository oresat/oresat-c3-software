''''MAX7310 GPIO Expander driver'''


from enum import IntEnum
from dataclasses import dataclass

from smbus2 import SMBus, i2c_msg


class Max7310Reg(IntEnum):
    '''MAX7310 register addresses'''

    INPUT = 0x00
    '''Input port register. Read byte.'''
    ODR = 0x01
    '''Output port register. Read/write byte.'''
    POL = 0x02
    '''Polarity inversion register. Read/write byte.'''
    MODE = 0x03
    '''Configuration register. Read/write byte.'''
    TIMEOUT = 0x04
    '''Timeout register. Read/write byte.'''


class Max7310Error(Exception):
    '''Error with Max7310'''


@dataclass
class Max7310Config:
    odr: int = 0
    pol: int = 0
    iomode: int = 0
    timeout: int = 0


@dataclass
class Max7310Status:
    opr: int = 0
    pol: int = 0
    mode: int = 0
    timeout: int = 0


class Max7310:
    ''''MAX7310 GPIO Expander driver'''

    ADDR_MIN = 8
    ADDR_MAX = 64
    ADDRESSES = list(range(ADDR_MIN, ADDR_MAX + 1))

    def __init__(self, bus_num: int):

        self._bus_num = bus_num

    def _i2c_read_reg(self, addr: int, reg: Max7310Reg) -> int:

        write = i2c_msg.write(addr, bytes([reg.value]))
        read = i2c_msg.read(addr, 1)

        with SMBus(self._bus_num) as bus:
            result = bus.i2c_rdwr(write, read)

        return int.from_bytes(result, 'little')

    def _i2c_write_reg(self, addr: int, reg: Max7310Reg, data: int):

        buf = bytes([reg.value])
        buf += data
        write = i2c_msg.write(addr, buf)

        with SMBus(self._bus_num) as bus:
            bus.i2c_rdwr(write)

    def _valid_pin(self, addr: int, pin_num: int):

        if pin_num <= 0 or pin_num > 8:
            raise Max7310Error(f'invalid pin_num: {pin_num}, must be between 0 and 7')
        if addr not in self.ADDRESSES:
            raise Max7310Error(f'addr 0x{addr:X} is not between 0x{self.ADDR_MIN:X} and '
                               f'0x{self.ADDR_MAX:X}')

    def start(self, addr: int, config: Max7310Config):

        self._i2c_write_reg(addr, Max7310Reg.ODR, config.odr)
        self._i2c_write_reg(addr, Max7310Reg.POL, config.pol)
        self._i2c_write_reg(addr, Max7310Reg.MODE, config.iomode)
        self._i2c_write_reg(addr, Max7310Reg.TIMEOUT, config.timeout)

    def stop(self, addr: int):

        # reset to input
        self._i2c_write_reg(addr, Max7310Reg.MODE, 0xFF)
        # reset reg to 0
        self._i2c_write_reg(addr, Max7310Reg.ODR, 0x00)
        # reset polarity
        self._i2c_write_reg(addr, Max7310Reg.POL, 0xF0)
        # reset timeout
        self._i2c_write_reg(addr, Max7310Reg.TIMEOUT, 0x01)

    def set_pin(self, addr: int, pin_num: int):

        self._valid_pin(addr, pin_num)

        result = self._i2c_read_reg(addr, Max7310Reg.ODR)
        result |= (1 << pin_num)
        self._i2c_write_reg(addr, Max7310Reg.ODR, result)

    def clear_pin(self, addr: int, pin_num: int):

        self._valid_pin(addr, pin_num)

        result = self._i2c_read_reg(addr, Max7310Reg.ODR)
        result &= ~(1 << pin_num)
        self._i2c_write_reg(addr, Max7310Reg.ODR, result)

    def status(self, addr) -> Max7310Status:

        return Max7310Status(
            self._i2c_read_reg(addr, Max7310Reg.INPUT.value),
            self._i2c_read_reg(addr, Max7310Reg.ODR.value),
            self._i2c_read_reg(addr, Max7310Reg.POL.value),
            self._i2c_read_reg(addr, Max7310Reg.MODE.value),
            self._i2c_read_reg(addr, Max7310Reg.TIMEOUT.value),
        )
