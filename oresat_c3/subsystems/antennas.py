"""Antennas subsystem."""

from time import sleep

from olaf import GPIO_IN, GPIO_OUT, Adc, Gpio, logger

from ..drivers.max7310 import Max7310, Max7310Error, MockMax7310


class Antennas:
    """Antennas subsystem."""

    _TIMEOUT_CONFIG = 1

    _I2C_BUS_NUM = 2 #reimplementation of whats in node_manager. Bad and should be fixed.	

    _READ_ANT_PIN = 0
    _FIRE_ANT_1_PIN = 1
    _FIRE_ANT_2_PIN = 2
    _TEST_ANT_PIN = 3
    
    def __init__(self, mock: bool = False):
        """
        Parameters
        ----------
        mock: bool
            Mock the hardware.
        """

        if not mock:
            self._pz_end_max7310 = Max7310(_I2C_BUS_NUM, 0x14)
            self._mz_end_max7310 = Max7310(_I2C_BUS_NUM, 0x15)
            self._mz_mid_max7310 = Max7310(_I2C_BUS_NUM, 0x16)
        else:
            self._pz_end_max7310 = Max7310(_I2C_BUS_NUM, 0x14, 0)
            self._mz_end_max7310 = Max7310(_I2C_BUS_NUM, 0x15, 0)
            self._mz_mid_max7310 = Max7310(_I2C_BUS_NUM, 0x16, 0)

        self._live_inputs = 1 << self._READ_ANT_PIN & 1 << self._TEST_ANT_PIN
        self._safe_inputs = self._live_inputs & 1 << self._FIRE_ANT_1_PIN & 1 << self._FIRE_ANT_2_PIN
        self.probe_cards()


    def probe_cards(self):
        """
            Looks for the endcards on the OPD. any that end cards that cannot be found or fail are set to None
        """
        try:
            if self._pz_end_max7310.is_valid:
                logger.info("Found plus z end card.")
                self._max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
            else:
                logger.info("Could not find plus z end card.")
                self._pz_end_max7310 = None
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup plus z end card with error.")
            self._pz_end_max7310 = None

        try:
            if self._mz_end_max7310.is_valid:
                logger.info("Found minus z end card.")
                self._max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
            else:
                logger.info("Could not find minus z end card.")
                self._mz_end_max7310 = None
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup minus z end card with error.")
            self._mz_end_max7310 = None

        try:
            if self._mz_mid_max7310.is_valid:
                logger.info("Found minus z mid card.")
                self._max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
            else:
                logger.info("Could not find minus z mid card.")
                self._mz_mid_max7310 = None
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup minus z mid card with error.")
            self._mz_mid_max7310 = None



    def deploy(self, timeout: int, delay_between: int):
        """
        Deploy the monopole antenna and then the helical.

        Wrapper ontop of deploy_monopole and deploy_helical.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        delay_between: int
            Delay between the monopole and helical deployments.
        """

        if self._pz_end_max7310 != None:
            logger.info("Attempting pos z end card firing.")
            self.deploy(timeout, self._pz_end_max7310)
            sleep(delay_between)
        if self._mz_end_max7310 != None:
            logger.info("Attempting minus z end card firing.")
            self.deploy(timeout, self._mz_end_max7310)
            sleep(delay_between)
        if self._mz_mid_max7310 != None:
            logger.info("Attempting minus z mid card firing.")
            self.deploy(timeout, self._mz_mid_max7310)

    def deploy(self, timeout: int, _max7310: Max7310):
        """
        Deploy using the specified MAX7310 chip.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        max: Max7310
            The MAX7310 to try to deploy with
        """

        try:
            _max7310.configure(0, 0, self._live_inputs, self._TIMEOUT_CONFIG)
            _max7310.output_set(self._FIRE_ANT_1_PIN)
            _max7310.output_set(self._FIRE_ANT_2_PIN)

            sleep(timeout)

            _max7310.output_clear(self._FIRE_ANT_1_PIN)
            _max7310.output_clear(self._FIRE_ANT_2_PIN)
            _max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Tried and failed to fire deployer.")


    # Commenting this out for now. We may want to reimplement this later.
    # def is_helical_good(self, good_threshold: int) -> bool:
    #     """
    #     Test the helical resistor.

    #     Parameters
    #     ----------
    #     good_threshold: int
    #         The good threshold (anything above this value is good) in millivolts for
    #         testing an antenna.

    #     Returns
    #     -------
    #     bool
    #         Helical is good.
    #     """

    #     self._gpio_test_helical.high()
    #     value = self._adc_helical.value
    #     self._gpio_test_helical.low()
    #     return value >= good_threshold