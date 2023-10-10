"""'
MAX7310 GPIO Expander driver

The MAX7310 is 2-wire-interfaced 8-bit I/O port expander with a reset.
"""

from enum import IntEnum

from smbus2 import SMBus, i2c_msg


class Max7310Reg(IntEnum):
    """
    MAX7310 register addresses

    Each register addresses is uint8.

    For all registers, except TIMEOUT, each bit in the register value corresponds to a port
    (e.g.: The LSB bit is for port 0, the MSB bit is for port 7).
    """

    INPUT_PORT = 0x00
    """
    Input port register. Read byte (all writes are ignored).

    Read to incomming logic level of all ports.
    """
    OUTPUT_PORT = 0x01
    """
    Output port register. Read/write byte.

    Set a bit to enable the output logic level as defined by the CONFIGURATION register.
    """
    POLARITY_INVERSION = 0x02
    """
    Polarity inversion register. Read/write byte.

    Set a bit to invert the corresponding pin polarity.
    """
    CONFIGURATION = 0x03
    """
    Configuration register. Read/write byte.

    Set bit to set corresponding pin to a input or clear bit to set corresponding pin to an output.
    """
    TIMEOUT = 0x04
    """
    Timeout register. Read/write byte.

    Set the LSB bit to enable the SDA reset timeout or clear that bit to disable the timeout.
    """


class Max7310Error(Exception):
    """Error with `Max7310`"""


class Max7310:
    """'MAX7310 GPIO Expander driver"""

    ADDR_MIN = 8
    ADDR_MAX = 64
    ADDRESSES = list(range(ADDR_MIN, ADDR_MAX + 1))

    def __init__(self, bus_num: int, addr: int, mock: bool = False):
        """
        Parameters
        ----------
        bus: int
            The I2C bus.
        mock: bool
            Mock the MAX7310.
        """

        if addr < self.ADDR_MIN or addr > self.ADDR_MAX:
            raise Max7310Error(
                f"self._addr 0x{addr:X} is not between 0x{self.ADDR_MIN:X} "
                f"and 0x{self.ADDR_MAX:X}"
            )

        self._mock = mock
        self._mock_regs = [0x00, 0x00, 0xF0, 0xFF, 0x01]  # default values according to spec
        self._bus_num = bus_num
        self._addr = addr

    def _i2c_read_reg(self, reg: Max7310Reg) -> int:
        if self._mock:
            result = self._mock_regs[reg.value]
        else:
            write = i2c_msg.write(self._addr, [reg.value])
            read = i2c_msg.read(self._addr, 1)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write, read)
            except (TimeoutError, OSError):
                raise Max7310Error(f"MAX7310 at address 0x{self._addr:02X} does not exist")

            result = list(read)[0]

        return result

    def _i2c_write_reg(self, reg: Max7310Reg, data: int):
        if data < 0 or data > 0xFF:
            raise Max7310Error("i2c write data must be between 0x00 and 0xFF")

        if self._mock:
            self._mock_regs[reg.value] = data
        else:
            buf = [reg.value, data]
            write = i2c_msg.write(self._addr, buf)

            try:
                with SMBus(self._bus_num) as bus:
                    bus.i2c_rdwr(write)
            except (TimeoutError, OSError):
                raise Max7310Error(f"MAX7310 at address 0x{self._addr:02X} does not exist")

    def _valid_pin(self, pin_num: int):
        if pin_num <= 0 or pin_num > 8:
            raise Max7310Error(f"invalid pin_num: {pin_num}, must be between 0 and 7")

    def configure(
        self, output_port: int, polarity_inversion: int, configuration: int, timeout: int
    ):
        """
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
        """

        self._i2c_write_reg(Max7310Reg.OUTPUT_PORT, output_port)
        self._i2c_write_reg(Max7310Reg.POLARITY_INVERSION, polarity_inversion)
        self._i2c_write_reg(Max7310Reg.CONFIGURATION, configuration)
        self._i2c_write_reg(Max7310Reg.TIMEOUT, timeout)

    def reset(self):
        """Reset the registers of the MAX7310 back to the default values."""

        # reset to defaults
        self._i2c_write_reg(Max7310Reg.CONFIGURATION, 0xFF)
        self._i2c_write_reg(Max7310Reg.OUTPUT_PORT, 0x00)
        self._i2c_write_reg(Max7310Reg.POLARITY_INVERSION, 0xF0)
        self._i2c_write_reg(Max7310Reg.TIMEOUT, 0x01)

    def output_set(self, pin_num: int):
        """
        Set a output pin / port.

        Parameters
        ----------
        pin_num: int
            The pin / port to set.
        """

        self._valid_pin(pin_num)

        result = self._i2c_read_reg(Max7310Reg.OUTPUT_PORT)
        result |= 1 << pin_num
        self._i2c_write_reg(Max7310Reg.OUTPUT_PORT, result)

    def output_clear(self, pin_num: int):
        """
        Clear a output pin / port.

        Parameters
        ----------
        pin_num: int
            The pin / port to clear.
        """

        self._valid_pin(pin_num)

        result = self._i2c_read_reg(Max7310Reg.OUTPUT_PORT)
        result &= ~(1 << pin_num)
        self._i2c_write_reg(Max7310Reg.OUTPUT_PORT, result)

    def output_status(self, pin_num: int) -> bool:
        """
        Get the status of a output pin.

        Parameters
        ----------
        pin_num: int
            The pin / port to get the status of.
        """

        result = self._i2c_read_reg(Max7310Reg.OUTPUT_PORT)
        return bool((result >> pin_num) & 0x01)

    def _mock_input_set(self, pin_num: int):
        """
        Set a input pin / port when mocking.

        Parameters
        ----------
        pin_num: int
            The pin / port to set.
        """

        if not self._mock:
            raise Max7310Error("cannot se _mock_input_set went not mocking")

        self._valid_pin(pin_num)

        result = self._i2c_read_reg(Max7310Reg.INPUT_PORT)
        result |= 1 << pin_num
        self._i2c_write_reg(Max7310Reg.INPUT_PORT, result)

    def _mock_input_clear(self, pin_num: int):
        """
        Clear a intput pin / port when mocking.

        Parameters
        ----------
        pin_num: int
            The pin / port to clear.
        """

        if not self._mock:
            raise Max7310Error("cannot se _mock_input_set went not mocking")

        self._valid_pin(pin_num)

        result = self._i2c_read_reg(Max7310Reg.INPUT_PORT)
        result &= ~(1 << pin_num)
        self._i2c_write_reg(Max7310Reg.INPUT_PORT, result)

    def input_status(self, pin_num: int) -> bool:
        """
        Get the status of a input pin.

        Parameters
        ----------
        pin_num: int
            The pin / port to get the status of.
        """

        result = self._i2c_read_reg(Max7310Reg.INPUT_PORT)
        return bool((result >> pin_num) & 0x01)

    @property
    def input_port(self) -> int:
        """int: Value from the input port register."""

        return self._i2c_read_reg(Max7310Reg.INPUT_PORT)

    @property
    def output_port(self) -> int:
        """int: Value from the output port register."""

        return self._i2c_read_reg(Max7310Reg.OUTPUT_PORT)

    @property
    def polarity_inversion(self) -> int:
        """int: Value from the polarity inversion register."""

        return self._i2c_read_reg(Max7310Reg.POLARITY_INVERSION)

    @property
    def configuration(self) -> int:
        """int: Value from the configuration register."""

        return self._i2c_read_reg(Max7310Reg.CONFIGURATION)

    @property
    def timeout(self) -> int:
        """int: Value from the timeout register."""

        return self._i2c_read_reg(Max7310Reg.TIMEOUT)

    @property
    def is_valid(self) -> bool:
        """bool: Is the max7310 valid."""

        try:
            self._i2c_read_reg(Max7310Reg.INPUT_PORT)
        except Max7310Error:
            return False

        return True
