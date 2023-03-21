''''
MAX7310 GPIO Expander driver

The MAX7310 is 2-wire-interfaced 8-bit I/O port expander with a reset.
'''

from enum import IntEnum

from smbus2 import SMBus, i2c_msg


class Max7310Reg(IntEnum):
    '''
    MAX7310 register addresses

    Each register addresses is uint8.

    For all registers, except TIMEOUT, each bit in the register value corresponds to a port
    (e.g.: The LSB bit is for port 0, the MSB bit is for port 7).
    '''

    INPUT_PORT = 0x00
    '''
    Input port register. Read byte (all writes are ignored).

    Read to incomming logic level of all ports.
    '''
    OUTPUT_PORT = 0x01
    '''
    Output port register. Read/write byte.

    Set a bit to enable the output logic level as defined by the CONFIGURATION register.
    '''
    POLARITY_INVERSION = 0x02
    '''
    Polarity inversion register. Read/write byte.

    Set a bit to invert the corresponding pin polarity.
    '''
    CONFIGURATION = 0x03
    '''
    Configuration register. Read/write byte.

    Set bit to set corresponding pin to a input or clear bit to set corresponding pin to an output.
    '''
    TIMEOUT = 0x04
    '''
    Timeout register. Read/write byte.

    Set the LSB bit to enable the SDA reset timeout or clear that bit to disable the timeout.
    '''


class Max7310Error(Exception):
    '''Error with Max7310'''


class Max7310:
    ''''MAX7310 GPIO Expander driver'''

    ADDR_MIN = 8
    ADDR_MAX = 64
    ADDRESSES = list(range(ADDR_MIN, ADDR_MAX + 1))

    def __init__(self, bus_num: int, addr: int, mock: bool = False):

        if addr < self.ADDR_MIN or addr > self.ADDR_MAX:
            raise Max7310Error(f'self._addr 0x{self._addr:X} is not between 0x{self.ADDR_MIN:X} '
                               f'and 0x{self.ADDR_MAX:X}')

        self._mock = mock
        self._mock_regs = {1: 0x00, 2: 0xF0, 3: 0xFF, 4: 0x01}
        self._bus_num = bus_num
        self._addr = addr
        self._enabled = False

    def _i2c_read_reg(self, reg: Max7310Reg) -> int:

        if self._mock:
            result = self._mock_regs[reg]
        else:
            write = i2c_msg.write(self._addr, bytes([reg.value]))
            read = i2c_msg.read(self._addr, 1)

            with SMBus(self._bus_num) as bus:
                result = bus.i2c_rdwr(write, read)

        return int.from_bytes(result, 'little')

    def _i2c_write_reg(self, reg: Max7310Reg, data: int):

        if self._mock:
            self._mock_regs[reg] = data
        else:
            buf = bytes([reg.value])
            buf += data
            write = i2c_msg.write(self._addr, buf)

            with SMBus(self._bus_num) as bus:
                bus.i2c_rdwr(write)

    def _valid_pin(self, pin_num: int):

        if pin_num <= 0 or pin_num > 8:
            raise Max7310Error(f'invalid pin_num: {pin_num}, must be between 0 and 7')

    def configure(self, output_port: int, polarity_inversion: int, configuration: int,
                  timeout: int):
        '''
        Configure the MAX7310 registers.

        Parameters
        ----------
        output_port: int
            The value to write to the output port register.
        polarity_inversion: int
            The value to write to the polarity inversion register.
        configuration: int
            The value to write to the configuration register.
        timeout: : int
            The value to write to the timeout register.
        '''

        self._i2c_write_reg(self._addr, Max7310Reg.OUTPUT_PORT, output_port)
        self._i2c_write_reg(self._addr, Max7310Reg.POLARITY_INVERSION, polarity_inversion)
        self._i2c_write_reg(self._addr, Max7310Reg.CONFIGURATION, configuration)
        self._i2c_write_reg(self._addr, Max7310Reg.TIMEOUT, timeout)

        self._enabled = True

    def reset(self):
        '''Reset the registers of the MAX7310 back to the default values.'''

        # reset to defaults
        self._i2c_write_reg(self._addr, Max7310Reg.CONFIGURATION, 0xFF)
        self._i2c_write_reg(self._addr, Max7310Reg.OUTPUT_PORT, 0x00)
        self._i2c_write_reg(self._addr, Max7310Reg.POLARITY_INVERSION, 0xF0)
        self._i2c_write_reg(self._addr, Max7310Reg.TIMEOUT, 0x01)

        self._enabled = False

    def set_pin(self, pin_num: int):
        '''
        Set a pin value.

        Parameters
        ----------
        pin_num: int
            The pin / port to set.
        '''

        self._valid_pin(self._addr, pin_num)

        result = self._i2c_read_reg(self._addr, Max7310Reg.OUTPUT_PORT)
        result |= (1 << pin_num)
        self._i2c_write_reg(self._addr, Max7310Reg.OUTPUT_PORT, result)

    def clear_pin(self, pin_num: int):
        '''
        Clear a pin value.

        Parameters
        ----------
        pin_num: int
            The pin / port to clear.
        '''

        self._valid_pin(self._addr, pin_num)

        result = self._i2c_read_reg(self._addr, Max7310Reg.OUTPUT_PORT)
        result &= ~(1 << pin_num)
        self._i2c_write_reg(self._addr, Max7310Reg.OUTPUT_PORT, result)

    @property
    def input_port(self) -> int:
        '''int: Value from the input port register.'''

        return self._i2c_read_reg(self._addr, Max7310Reg.INPUT_PORT.value)

    @property
    def output_port(self) -> int:
        '''int: Value from the output port register.'''

        return self._i2c_read_reg(self._addr, Max7310Reg.OUTPUT_PORT.value)

    @property
    def polarity_inversion(self) -> int:
        '''int: Value from the polarity inversion register.'''

        return self._i2c_read_reg(self._addr, Max7310Reg.POLARITY_INVERSION.value)

    @property
    def configuration(self) -> int:
        '''int: Value from the configuration register.'''

        return self._i2c_read_reg(self._addr, Max7310Reg.CONFIGURATION.value)

    @property
    def timeout(self) -> int:
        '''int: Value from the timeout register.'''

        return self._i2c_read_reg(self._addr, Max7310Reg.TIMEOUT.value)

    @property
    def is_enabled(self) -> bool:
        '''bool: Is the max7310 enabled.'''

        return self._enabled

    @property
    def is_valid(self) -> bool:
        '''bool: Is the max7310 valid.'''

        try:
            self._i2c_read_reg(self._addr, Max7310Reg.INPUT_PORT.value)
        except Exception:
            return False

        return True
