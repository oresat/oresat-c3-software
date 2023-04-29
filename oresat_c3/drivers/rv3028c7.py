'''
RV-3082-C7 RTC driver

The RV-3082-C7 is an extreme low power real-time clock module with I2C-bus interface.
'''

from enum import IntEnum

from smbus2 import SMBus, i2c_msg


class Rv3082c7Reg(IntEnum):

    SECONDS = 0x00
    MINUTES = 0x01
    HOURS = 0x02
    WEEKDAYS = 0x03
    DATE = 0x04
    MONTH = 0x05
    YEAR = 0x06
    MINUTES_ALARM = 0x07
    HOURS_ALARM = 0x08
    WEEKDAYS_ALARM = 0x09
    TIMER_VALUE = 0x0A
    TIMER_STATUS = 0x0C
    STATUS = 0x0E
    CONTROL = 0x0F
    GP_BITS = 0x11
    CLOCK_INT_MASK = 0x12
    EVENT_CONTROL = 0x13
    COUNT_TS = 0x14
    SECONDS_TS = 0x15
    MINUTES_TS = 0x16
    HOURS_TS = 0x17
    DATE_TS = 0x18
    MONTH_TS = 0x19
    YEAR_TS = 0x1A
    UNIX_TIME = 0x1B
    USER_RAM = 0x1F
    PASSWORD = 0x21
    EE_ADDRESS = 0x25
    EE_DATA = 0x26
    EE_COMMAND = 0x27
    ID = 0x28

    @property
    def size(self) -> int:
        '''int: Get ths size of value in register in bytes'''

        r = 1

        if self.value in [Rv3082c7Reg.USER_RAM, Rv3082c7Reg.PASSWORD]:
            r = 4
        elif self.value in [Rv3082c7Reg.TIMER_VALUE, Rv3082c7Reg.TIMER_STATUS,
                            Rv3082c7Reg.CONTROL, Rv3082c7Reg.USER_RAM]:
            r = 2

        return r


class Rv3082c7Error(Exception):
    '''Error with `Rv7310C7`'''


class Rv3082c7:
    ''''RV-3082-C7 RTC driver'''

    ADDR = 0x52

    def __init__(self, bus_num: int, mock: bool = False):
        '''
        Parameters
        ----------
        bus: int
            The I2C bus.
        mock: bol
            Mock the RV-3082-C7.
        '''

        self._mock = mock
        self._mock_regs = bytearray([0] * 0x29)
        self._bus_num = bus_num

    def _i2c_read_reg(self, reg: Rv3082c7Reg) -> int:

        if self._mock:
            raw = self._mock_regs[reg.value:reg.value + reg.size]
        else:
            write = i2c_msg.write(self.ADDR, [reg.value])
            read = i2c_msg.read(self.ADDR, reg.size)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write, read)
            except OSError:
                raise Rv3082c7Error(f'failed to read from reg {reg}')

            raw = bytes(read.buf)

        return int.from_bytes(raw, 'little')

    def _i2c_write_reg(self, reg: Rv3082c7Reg, value: int):

        raw = value.to_bytes(reg.size, 'little')

        if self._mock:
            self._mock_regs[reg.value:reg.value + reg.size - 1] = raw
        else:
            buf = reg.value.to_bytes(1, 'little') + raw
            write = i2c_msg.write(self.ADDR, buf)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write)
            except OSError:
                raise Rv3082c7Error(f'failed to write value 0x{value:X} to reg {reg}')

            read = self._i2c_read_reg(reg)
            if read != value:
                raise Rv3082c7Error(f'read after write did not match; wrote 0x{value:X}, read '
                                    f'back 0x{read:X}')

    @property
    def unix_time(self) -> float:
        '''float: unix time in seconds'''

        return float(self._i2c_read_reg(Rv3082c7Reg.UNIX_TIME))

    @unix_time.setter
    def unix_time(self, value: int or float):

        self._i2c_write_reg(Rv3082c7Reg.UNIX_TIME, int(value))
