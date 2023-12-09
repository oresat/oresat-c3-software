"""'
SI41xx RF Synthesizer driver.
"""

from enum import IntEnum
from typing import Union

from olaf import Gpio


class Si41xxRegister(IntEnum):
    """SI41XX register addresses."""

    CONFIG = 0
    PHASE_GAIN = 1
    PWRDOWN = 2
    RF1_NDIV = 3
    RF2_NDIV = 4
    IF_NDIV = 5
    RF1_RDIV = 6
    RF2_RDIV = 7
    IF_RDIV = 8


class Si41xxState(IntEnum):
    """SI41XX states."""

    UNINIT = 1
    """Not initialized"""
    STOP = 2
    """Stopped"""
    READY = 3
    """Ready"""


class Si41xxIfdiv(IntEnum):
    """Values for if_div bits in config register"""

    DIV1 = 0
    DIV2 = 1
    DIV4 = 3
    DIV8 = 4


class Si41xxAuxSel(IntEnum):
    """Values for aux_sel bits in config register"""

    LOW = 1
    LOCKDET = 3


class Si41xxError(Exception):
    """Error with `Si41xx`"""


class Si41xx:
    """SI41xx RF Synthesizer driver."""

    MAX_PHASEDET = 1_000_000
    MIN_PHASEDET = 10_000

    _MSG_SIZE = 22  # lsb 4 bits for reg addr, msb 18 bits for data
    _MSG_MSB = 1 << 21
    _DATA_MASK = 0x3_FF_FF

    def __init__(
        self,
        sen_pin: str,
        sclk_pin: str,
        sdata_pin: str,
        auxout_pin: str,
        ref_freq: int,
        if_div: Si41xxIfdiv,
        if_n: int,
        if_r: int,
        mock: bool = False,
    ):
        """
        Paramters
        ---------
        sen_pin: int
            Serial enable pin.
        sclk_pin: int
            Serial clock pin.
        sdata_pin: int
            Serial data pin.
        auxout_pin: int
            The auxout pin.
        ref_freq: int
            Reference frequency in Hz.
        if_div: Si41xxIfdiv
            IF DIV mode.
        if_n: int
            IF N-Divider.
        if_r: int
            IF R-Divider.
        mock: bool
            Optional flag to mock SI41xx.
        """

        self._state = Si41xxState.UNINIT

        self._sen_gpio = Gpio(sen_pin, mock)
        self._sclk_gpio = Gpio(sclk_pin, mock)
        self._sdata_gpio = Gpio(sdata_pin, mock)
        self._auxout_gpio = Gpio(auxout_pin, mock)
        self._ref_freq = ref_freq
        self._if_div = if_div
        self._if_n = if_n
        self._if_r = if_r
        self._mock = mock

        self._pbib = False
        self._pbrb = False

    def _write_reg(self, reg: Si41xxRegister, data: int):
        """
        Bit bang the register over serial

        Parameters
        ----------
        reg: Si41xxRegister
            The register to write to.
        data: int
            the data to write. Should
        """

        if data > self._DATA_MASK:
            raise Si41xxError(f"data must be less than 0x{self._DATA_MASK:X}, was 0x{data:X}")

        word = reg.value | ((data & self._DATA_MASK) << 4)

        self._sen_gpio.low()

        # bit bang from MSB down
        for _ in range(self._MSG_SIZE, 0, -1):
            self._sclk_gpio.low()

            if word & self._MSG_MSB:
                self._sdata_gpio.high()
            else:
                self._sdata_gpio.low()

            self._sclk_gpio.high()
            word <<= 1

        self._sclk_gpio.low()
        self._sen_gpio.high()
        self._sclk_gpio.high()

    def calc_div(self, freq: int) -> tuple[int, int]:
        """
        This function calculates N and R division values needed to provided the specified frequency
        from the reference frequency defined in the device configuration.

        Parameters
        ----------
        freq: int
            Desired output frequency

        Returns
        -------
        int, int
            Calculated N-Divider value
            Calculated R-Divider value
        """
        if freq == 0:
            raise Si41xxError("freq must be a non-zero value")

        phasedet = self._ref_freq
        gcd = freq

        # Find GCD of both frequencies
        while phasedet != gcd:
            if phasedet > gcd:
                phasedet -= gcd
            else:
                gcd -= phasedet

        # Divide until frequency is less than the maximum
        while phasedet >= self.MAX_PHASEDET:
            phasedet //= 2
        if phasedet < self.MIN_PHASEDET:
            raise Si41xxError("failed to find values within phase detector frequency bounds")

        # Calculate needed N and R values
        ndiv = freq // phasedet
        rdiv = self._ref_freq // phasedet

        if ndiv > 0xFF_FF or rdiv > 0x1F_FF:
            raise Si41xxError("calc_div values are not within bounds of programmable values")

        return ndiv, rdiv

    def start(self):
        """Configures and activates SI41XX Driver peripheral"""

        if self._state == Si41xxState.READY:
            raise Si41xxError("Already started")

        self._pbib = False
        self._pbrb = False

        self._set_config_reg(False, True, False, False, self._if_div, Si41xxAuxSel.LOCKDET)
        self._write_reg(Si41xxRegister.PHASE_GAIN, 0)
        self._set_phase_pwrdown_reg(self._pbrb, self._pbib)

        self._pbib = True
        self._set_if_ndiv_reg(self._if_n)
        self._set_if_rdiv_reg(self._if_r)

        self._set_phase_pwrdown_reg(self._pbrb, self._pbib)

        self._state = Si41xxState.READY

    def stop(self):
        """Deactivates the SI41XX Complex Driver peripheral."""

        self._pbib = False
        self._pbrb = False

        if self._state == Si41xxState.READY:
            self._set_phase_pwrdown_reg(self._pbrb, self._pbib)
            self._write_reg(Si41xxRegister.CONFIG, 0)

        self._state = Si41xxState.STOP

    def _set_config_reg(
        self,
        rfpwr: bool,
        autokp: bool,
        autopdb: bool,
        lprw: bool,
        if_div: Union[Si41xxIfdiv, int],
        aux_sel: Union[Si41xxAuxSel, int],
    ):
        """Set the Config register"""

        value = 0

        value |= rfpwr << 1
        value |= autokp << 2
        value |= autopdb << 3
        value |= lprw << 5
        if isinstance(if_div, Si41xxAuxSel):
            value |= if_div.value << 10
        else:
            value |= if_div << 10
        if isinstance(aux_sel, Si41xxAuxSel):
            value |= aux_sel.value << 12
        else:
            value |= aux_sel << 12

        self._write_reg(Si41xxRegister.CONFIG, value)

    def _set_phase_gain_reg(self, kp1: int, kp2: int, kpi: int):
        """Set the Phase Detector Gain register"""

        if kp1 < 0 or kp1 > 0x3:
            raise Si41xxError("kp1 must be between 0 and 3")
        if kp2 < 0 or kp2 > 0x3:
            raise Si41xxError("kp2 must be between 0 and 3")
        if kpi < 0 or kpi > 0x3:
            raise Si41xxError("kpi must be between 0 and 3")

        value = 0

        value |= kp1
        value |= kp2 << 2
        value |= kpi << 4

        self._write_reg(Si41xxRegister.PHASE_GAIN, value)

    def _set_phase_pwrdown_reg(self, pbrb: bool, pbib: bool):
        """Set the Powerdown register"""

        value = 0

        value |= int(pbrb)
        value |= int(pbib) << 1

        self._write_reg(Si41xxRegister.PWRDOWN, value)

    def _set_rf1_ndiv_reg(self, value: int):
        """Set the RF1 N-Divider register"""

        if value < 0 or value > 0x3_FF_FF:
            raise Si41xxError(f"rf1_ndiv value must be between 0 and {0x3_FF_FF}")

        self._write_reg(Si41xxRegister.RF1_NDIV, value)

    def _set_rf2_ndiv_reg(self, value: int):
        """Set the RF2 N-Divider register"""

        if value < 0 or value > 0x1_FF_FF:
            raise Si41xxError(f"rf2_ndiv value must be between 0 and {0x1_FF_FF}")

        self._write_reg(Si41xxRegister.RF2_NDIV, value)

    def _set_if_ndiv_reg(self, value: int):
        """Set the IF N-Divider register"""

        if value < 0 or value > 0xFF_FF:
            raise Si41xxError(f"if_ndiv value must be between 0 and {0xFF_FF}")

        self._write_reg(Si41xxRegister.IF_NDIV, value)

    def _set_rf1_rdiv_reg(self, value: int):
        """Set the RF1 R-Divider register"""

        if value < 0 or value > 0x1_FF_FF:
            raise Si41xxError(f"rf1_rdiv value must be between 0 and {0x1_FF_FF}")

        self._write_reg(Si41xxRegister.RF1_RDIV, value)

    def _set_rf2_rdiv_reg(self, value: int):
        """Set the RF2 R-Divider register"""

        if value < 0 or value > 0x1_FF_FF:
            raise Si41xxError(f"rf2_rdiv value must be between 0 and {0x1_FF_FF}")

        self._write_reg(Si41xxRegister.RF2_RDIV, value)

    def _set_if_rdiv_reg(self, value: int):
        """Set the IF R-Divider register"""

        if value < 0 or value > 0x1_FF_FF:
            raise Si41xxError(f"if_rdiv value must be between 0 and {0x1_FF_FF}")

        self._write_reg(Si41xxRegister.IF_RDIV, value)

    def set_if(self, freq: int):
        """Sets IF N and R values to provide the desired frequency"""

        self._if_n, self._if_r = self.calc_div(freq << self._if_div)

        self._pbib = False
        self._set_phase_pwrdown_reg(self._pbrb, self._pbib)
        self._set_if_ndiv_reg(self._if_n)
        self._set_if_rdiv_reg(self._if_r)
        self._pbib = True
        self._set_phase_pwrdown_reg(self._pbrb, self._pbib)

    def set_if_div(self, div: Si41xxIfdiv):
        """Sets IF divider value."""

        self._if_div = div

        # this is how the old C code did this
        self._set_config_reg(False, False, False, False, div, 0)
