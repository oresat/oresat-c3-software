'''
RV-3082-CV RTC driver

The RV-3082-CV is an extreme low power real-time clock module with I2C-bus interface driver.
'''

from enum import IntEnum

from smbus2 import SMBus, i2c_msg


class Rv3082cvReg(IntEnum):

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

        if self.value in [Rv3082cvReg.USER_RAM, Rv3082cvReg.PASSWORD]:
            r = 4
        elif self.value in [Rv3082cvReg.TIMER_VALUE, Rv3082cvReg.TIMER_STATUS,
                            Rv3082cvReg.CONTROL, Rv3082cvReg.USER_RAM]:
            r = 2

        return r

    def to_bytes(self) -> bytes:
        '''bytes: Get the register value as a bytes'''

        return self.value.to_bytes(1, 'little')


class Rv3082cv:
    ''''RV-3082-CV RTC driver'''

    ADDR = 0x52

    def __init__(self, bus_num: int, mock: bool = False):

        self._mock = mock
        self._mock_regs = bytearray([0] * 0x29)
        self._bus_num = bus_num

    def _i2c_read_reg(self, reg: Rv3082cvReg) -> int:

        if self._mock:
            result = self._mock_regs[reg.value:reg.value + reg.size]
        else:
            write = i2c_msg.write(self.ADDR, reg.to_bytes())
            read = i2c_msg.read(self.ADDR, reg.size)

            with SMBus(self._bus_num) as bus:
                result = bus.i2c_rdwr(write, read)

        return int.from_bytes(result, 'little')

    def _i2c_write_reg(self, reg: Rv3082cvReg, data: int):

        if self._mock:
            self._mock_regs[reg.value:reg.value + len(data) - 1] = data
        else:
            buf = reg.value
            buf += data.to_bytes(reg.size, 'little')
            write = i2c_msg.write(self.ADDR, buf)

            with SMBus(self._bus_num) as bus:
                bus.i2c_rdwr(write)

    @property
    def unix_time(self) -> float:
        '''float: unix time in seconds'''

        return float(self._i2c_read_reg(Rv3082cvReg.UNIX_TIME))

    @unix_time.setter
    def unix_time(self, value: int | float):

        self._i2c_write_reg(Rv3082cvReg.UNIX_TIME, int(value))
