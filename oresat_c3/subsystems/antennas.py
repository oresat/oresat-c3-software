"""Antennas subsystem."""

from time import sleep

from olaf import GPIO_IN, GPIO_OUT, Adc, Gpio


class Antennas:
    """Antennas subsystem."""

    def __init__(self, mock: bool = False):
        """
        Parameters
        ----------
        mock: bool
            Mock the hardware.
        """

        self._gpio_monopole_1 = Gpio("FIRE_ANTENNAS_1", mock)
        self._gpio_monopole_2 = Gpio("FIRE_ANTENNAS_2", mock)
        self._gpio_helical_1 = Gpio("FIRE_HELICAL_1", mock)
        self._gpio_helical_2 = Gpio("FIRE_HELICAL_2", mock)

        self._gpio_test_monopole = Gpio("TEST_ANTENNAS", mock)
        self._gpio_test_helical = Gpio("TEST_HELICAL", mock)

        self._adc_monopole = Adc(4, mock)
        self._adc_helical = Adc(5, mock)

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

        self.deploy_monopole(timeout)
        sleep(delay_between)
        self.deploy_helical(timeout)

    def deploy_helical(self, timeout: int):
        """
        Deploy only the helical.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """

        self._gpio_helical_1.mode = GPIO_OUT
        self._gpio_helical_2.mode = GPIO_OUT

        self._gpio_helical_1.high()
        self._gpio_helical_2.high()
        sleep(timeout)
        self._gpio_helical_1.low()
        self._gpio_helical_2.low()

        self._gpio_helical_1.mode = GPIO_IN
        self._gpio_helical_2.mode = GPIO_IN

    def deploy_monopole(self, timeout: int):
        """
        Deploy only the monopole.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """

        self._gpio_monopole_1.mode = GPIO_OUT
        self._gpio_monopole_2.mode = GPIO_OUT

        self._gpio_monopole_1.high()
        self._gpio_monopole_2.high()
        sleep(timeout)
        self._gpio_monopole_1.low()
        self._gpio_monopole_2.low()

        self._gpio_monopole_1.mode = GPIO_IN
        self._gpio_monopole_2.mode = GPIO_IN

    def is_helical_good(self, good_threshold: int) -> bool:
        """
        Test the helical resistor.

        Parameters
        ----------
        good_threshold: int
            The good threshold (anything above this value is good) in millivolts for
            testing an antenna.

        Returns
        -------
        bool
            Helical is good.
        """

        self._gpio_test_helical.high()
        value = self._adc_helical.value
        self._gpio_test_helical.low()
        return value >= good_threshold

    def is_monopole_good(self, good_threshold: int) -> bool:
        """
        Test the monopole resistor.

        Parameters
        ----------
        good_threshold: int
            The good threshold (anything above this value is good) in millivolts for
            testing an antenna.

        Returns
        -------
        bool
            Monopole is good.
        """

        self._gpio_test_monopole.high()
        value = self._adc_monopole.value
        self._gpio_test_monopole.low()
        return value >= good_threshold
