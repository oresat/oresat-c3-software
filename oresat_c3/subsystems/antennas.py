"""Antennas subsystem."""

import time
from typing import TYPE_CHECKING

from gpiod.line import Direction, Value
from olaf import Adc, logger

from oresat_c3.subsystems._gpio import request_gpio_input, request_gpio_output

if TYPE_CHECKING:
    import gpiod


class MockAntenna:
    def deploy(self, timeout: int):
        pass

    def is_good(self, good_threshold: int) -> bool:
        logger.info(f"{self.name} is good")
        return True


class Monopole:
    def __init__(self):
        """Request gpio."""
        self._gpio_monopole_1: gpiod.LineRequest = request_gpio_input(
            "/dev/gpiochip3", 20, "FIRE_ANTENNAS_1"
        )

        self._gpio_monopole_2: gpiod.LineRequest = request_gpio_input(
            "/dev/gpiochip2", 21, "FIRE_ANTENNAS_2"
        )

        self._gpio_test_monopole: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip2", 17, "TEST_ANTENNAS"
        )

        self._adc_monopole = Adc(4, False)

    def deploy(self, timeout: int):
        """
        Deploy the monopole antenna.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """

        self._gpio_monopole_1.reconfigure_lines(
            config={
                self._gpio_monopole_1.offsets[0]: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE
                )
            }
        )

        self._gpio_monopole_2.reconfigure_lines(
            config={
                self._gpio_monopole_2.offsets[0]: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE
                )
            }
        )

        self._gpio_monopole_1.set_value(self._gpio_monopole_1.offsets[0], Value.ACTIVE)
        self._gpio_monopole_2.set_value(self._gpio_monopole_2.offsets[0], Value.ACTIVE)
        time.sleep(timeout)
        self._gpio_monopole_1.set_value(
            self._gpio_monopole_1.offsets[0], Value.INACTIVE
        )
        self._gpio_monopole_2.set_value(
            self._gpio_monopole_2.offsets[0], Value.INACTIVE
        )

        self._gpio_monopole_1.reconfigure_lines(
            config={
                self._gpio_monopole_1.offsets[0]: gpiod.LineSettings(
                    direction=Direction.INPUT
                )
            }
        )

        self._gpio_monopole_2.reconfigure_lines(
            config={
                self._gpio_monopole_2.offsets[0]: gpiod.LineSettings(
                    direction=Direction.INPUT
                )
            }
        )
        pass

    def is_good(self, good_threshold: int) -> bool:
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

        self._gpio_test_monopole.set_value(
            self._gpio_test_monopole.offsets[0], Value.ACTIVE
        )
        value = self._adc_monopole.value
        self._gpio_test_monopole.set_value(
            self._gpio_test_monopole.offsets[0], Value.INACTIVE
        )
        return value >= good_threshold


class Helical:
    def __init__(self):
        """Request gpio."""
        self._gpio_helical_1: gpiod.LineRequest = request_gpio_input(
            "/dev/gpiochip2", 16, "FIRE_HELICAL_1"
        )

        self._gpio_helical_2: gpiod.LineRequest = request_gpio_input(
            "/dev/gpiochip2", 14, "FIRE_HELICAL_2"
        )

        self._gpio_test_helical: gpiod.LineRequest = request_gpio_output(
            "/dev/gpiochip2", 15, "TEST_HELICAL"
        )
        self._adc_helical = Adc(5, False)

    def deploy(self, timeout: int):
        """
        Deploy the antenna.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        """

        self._gpio_helical_1.reconfigure_lines(
            config={
                self._gpio_helical_1.offsets[0]: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE
                )
            }
        )

        self._gpio_helical_2.reconfigure_lines(
            config={
                self._gpio_helical_2.offsets[0]: gpiod.LineSettings(
                    direction=Direction.OUTPUT, output_value=Value.INACTIVE
                )
            }
        )

        self._gpio_helical_1.set_value(self._gpio_helical_1.offsets[0], Value.ACTIVE)
        self._gpio_helical_2.set_value(self._gpio_helical_2.offsets[0], Value.ACTIVE)
        time.sleep(timeout)
        self._gpio_helical_1.set_value(self._gpio_helical_1.offsets[0], Value.INACTIVE)
        self._gpio_helical_2.set_value(self._gpio_helical_2.offsets[0], Value.INACTIVE)

        self._gpio_helical_1.reconfigure_lines(
            config={
                self._gpio_helical_1.offsets[0]: gpiod.LineSettings(
                    direction=Direction.INPUT
                )
            }
        )

        self._gpio_helical_2.reconfigure_lines(
            config={
                self._gpio_helical_2.offsets[0]: gpiod.LineSettings(
                    direction=Direction.INPUT
                )
            }
        )

    def is_good(self, good_threshold: int) -> bool:
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

        self._gpio_test_helical.set_value(
            self._gpio_test_helical.offsets[0], Value.ACTIVE
        )
        value = self._adc_helical.value
        self._gpio_test_helical.set_value(
            self._gpio_test_helical.offsets[0], Value.INACTIVE
        )
        return value >= good_threshold


class Antennas:
    """Antennas subsystem."""

    def __init__(self, mock: bool = False):
        """
        Parameters
        ----------
        mock: bool
            Mock the hardware.
        """

        if mock:
            self.helical = MockAntenna()
            self.monopole = MockAntenna()
        else:
            self.helical = Helical()
            self.monopole = Monopole()

    def deploy(self, timeout: int, delay_between: int):
        """
        Deploy the monopole antenna and then the helical.

        Parameters
        ----------
        timeout: int
            How long the gpio lines are set high.
        delay_between: int
            Delay between the monopole and helical deployments.
        """

        logger.info("Deploying monopole antenna")
        self.monopole.deploy(timeout)
        time.sleep(delay_between)
        logger.info("Deploying helical antenna")
        self.helical.deploy(timeout)

    def deploy_helical(self, timeout: int):
        logger.info("Deploying helical antenna")
        self.helical.deploy(timeout)

    def deploy_monopole(self, timeout: int):
        logger.info("Deploying monopole antenna")
        self.monopole.deploy(timeout)

    def is_helical_good(self, good_threshold: int) -> bool:
        return self.helical.is_good(good_threshold)

    def is_monopole_good(self, good_threshold: int) -> bool:
        return self.monopole.is_good(good_threshold)
