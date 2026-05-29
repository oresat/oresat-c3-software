"""Antennas subsystem."""

from time import sleep

from olaf import GPIO_IN, GPIO_OUT, Adc, Gpio, logger

from ..drivers.max7310 import Max7310, Max7310Error, MockMax7310


class Antennas:
    """Antennas subsystem."""

    _TIMEOUT_CONFIG = 1

    _I2C_BUS_NUM = 2  # reimplementation of whats in node_manager. Bad and should be fixed.	

    _READ_ANT_PIN = 0
    _FIRE_ANT_1_PIN = 1
    _FIRE_ANT_2_PIN = 2
    _TEST_ANT_PIN = 3

    def __init__(self, mock: bool = False) -> None:
        """
        Parameters
        ----------
        mock: bool
            Mock the hardware.
        """
        self._mock = mock
        self._live_inputs = 1 << self._READ_ANT_PIN & 1 << self._TEST_ANT_PIN
        self._safe_inputs = (
            self._live_inputs & 1 << self._FIRE_ANT_1_PIN & 1 << self._FIRE_ANT_2_PIN
        )

        self._pz_end_max7310 = None
        self._mz_end_max7310 = None
        self._mz_mid_max7310 = None

        self.probe_pz_end()
        self.probe_mz_end()
        self.probe_mz_mid()

    def probe_pz_end(self) -> bool:
        """
        Attempt to define and confirm the existence of the plus z end card.
        """

        if not self._mock:
            self._pz_end_max7310 = Max7310(self._I2C_BUS_NUM, 0x14)
        else:
            self._pz_end_max7310 = Max7310(self._I2C_BUS_NUM, 0x14, 0)

        try:
            if self._pz_end_max7310.is_valid:
                logger.info("Found plus z end card.")
                self._pz_end_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
                return True
            else:
                logger.info("Could not find plus z end card.")
                self._pz_end_max7310 = None
                return False
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup plus z end card with error.")
            self._pz_end_max7310 = None
            return False

    def probe_mz_end(self) -> bool:
        """
        Attempt to define and confirm the existence of the minus z end card.
        """

        if not self._mock:
            self._mz_end_max7310 = Max7310(self._I2C_BUS_NUM, 0x15)
        else:
            self._mz_end_max7310 = Max7310(self._I2C_BUS_NUM, 0x15, 0)

        try:
            if self._mz_end_max7310.is_valid:
                logger.info("Found minus z end card.")
                self._mz_end_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
                return True
            else:
                logger.info("Could not find minus z end card.")
                self._mz_end_max7310 = None
                return False
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup minus z end card with error.")
            self._mz_end_max7310 = None
            return False

    def probe_mz_mid(self) -> bool:
        """
        Attempt to define and confirm the existence of the minus z mid card.
        """

        if not self._mock:
            self._mz_mid_max7310 = Max7310(self._I2C_BUS_NUM, 0x16)
        else:
            self._mz_mid_max7310 = Max7310(self._I2C_BUS_NUM, 0x16, 0)

        try:
            if self._mz_mid_max7310.is_valid:
                logger.info("Found minus z mid card.")
                self._mz_mid_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
                return True
            else:
                logger.info("Could not find minus z mid card.")
                self._mz_mid_max7310 = None
                return False
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Failed to setup minus z mid card with error.")
            self._mz_mid_max7310 = None
            return False

    def deploy(self, timeout: int, delay_between: int) -> None:
        """
        Deploy the plus z endcard (helical), then the minus z endcard (monopole), then the minus z midcard (ESI deployable solar wing).

        Wrapper ontop of deploy_pz_endcard, deploy_mz_endcard, and deploy_mz_midcard.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        delay_between: int
            Delay between the monopole and helical deployments.
        """
        logger.info("Attempting pos z end card firing.")
        self.deploy_pz_endcard(timeout)
        sleep(delay_between)
        logger.info("Attempting minus z end card firing.")
        self.deploy_mz_endcard(timeout)
        sleep(delay_between)
        logger.info("Attempting minus z mid card firing.")
        self.deploy_mz_midcard(timeout)

    def deploy_pz_endcard(self, timeout: int) -> None:
        """
        Try to deploy the positive z end card (Helical). If we have been unable to find this endcard, try to find it again.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """
        if self._pz_end_max7310 == None:
            if not self.probe_pz_end():
                return

        try:
            self._pz_end_max7310.configure(0, 0, self._live_inputs, self._TIMEOUT_CONFIG)
            self._pz_end_max7310.output_set(self._FIRE_ANT_1_PIN)
            self._pz_end_max7310.output_set(self._FIRE_ANT_2_PIN)
            sleep(timeout)

            self._pz_end_max7310.output_clear(self._FIRE_ANT_1_PIN)
            self._pz_end_max7310.output_clear(self._FIRE_ANT_2_PIN)
            self._pz_end_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Tried and failed to fire plus z end card deployer.")

    def deploy_mz_endcard(self, timeout: int) -> None:
        """
        Try to deploy the positive z end card (Helical). If we have been unable to find this endcard, try to find it again.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """
        if self._mz_end_max7310 == None:
            if not self.probe_mz_end():
                return

        try:
            self._mz_end_max7310.configure(0, 0, self._live_inputs, self._TIMEOUT_CONFIG)
            self._mz_end_max7310.output_set(self._FIRE_ANT_1_PIN)
            self._mz_end_max7310.output_set(self._FIRE_ANT_2_PIN)
            sleep(timeout)

            self._mz_end_max7310.output_clear(self._FIRE_ANT_1_PIN)
            self._mz_end_max7310.output_clear(self._FIRE_ANT_2_PIN)
            self._mz_end_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Tried and failed to fire minus z end card deployer.")

    def deploy_mz_midcard(self, timeout: int) -> None:
        """
        Try to deploy the positive z end card (Helical). If we have been unable to find this endcard, try to find it again.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """
        if self._mz_mid_max7310 == None:
            if not self.probe_mz_mid():
                return

        try:
            self._mz_mid_max7310.configure(0, 0, self._live_inputs, self._TIMEOUT_CONFIG)
            self._mz_mid_max7310.output_set(self._FIRE_ANT_1_PIN)
            self._mz_mid_max7310.output_set(self._FIRE_ANT_2_PIN)
            sleep(timeout)

            self._mz_mid_max7310.output_clear(self._FIRE_ANT_1_PIN)
            self._mz_mid_max7310.output_clear(self._FIRE_ANT_2_PIN)
            self._mz_mid_max7310.configure(0, 0, self._safe_inputs, self._TIMEOUT_CONFIG)
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.info(f"Tried and failed to fire minus z mid card deployer.")
