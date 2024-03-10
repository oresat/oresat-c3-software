"""
Everything todo with the OPD (OreSat Power Domain) functionality.

Every card, other than the solar cards, has a MAX7310 that can be used to turn the card or off.
"""

from enum import IntEnum
from time import sleep

from olaf import Adc, Gpio, logger

from ..drivers.max7310 import Max7310, Max7310Error


class OpdError(Exception):
    """Error with :py:class:`Opd` or :py:class:`OpdNode`"""


class OpdNodeState(IntEnum):
    """OPD node states"""

    DISABLED = 0
    """OPD Node is off"""
    ENABLED = 1
    """OPD Node is on"""
    FAULT = 2
    """Fault input is set for OPD node"""
    DEAD = 3
    """OPD node is consider dead (too many faults in a row)."""
    NOT_FOUND = 0xFF
    """OPD node is not found"""


class OpdNode:
    """
    Base class for all OPD nodes

    NOTE: CFC sensor node does not have UART enable pin.
    """

    _RESET_DELAY_S = 0.25

    _TIMEOUT_CONFIG = 1

    # these are consistent between all cards
    _NOT_FAULT_PIN = 2
    _ENABLE_PIN = 3
    _CB_RESET_PIN = 4

    def __init__(self, bus: int, name: str, addr: int, mock: bool = False):
        """
        Parameters
        ----------
        not_enable_pin: int
            Pin that enable the OPD subsystem.
        name: str
            Name of OPD node.
        bus: int
            The I2C bus.
        mock: bool
            Mock the OPD subsystem.
        """

        self._addr = addr
        self._name = name
        self._mock = mock
        self._max7310 = Max7310(bus, addr, mock)
        self._status = OpdNodeState.NOT_FOUND

    def __del__(self):
        try:
            self._max7310.output_clear(self._ENABLE_PIN)
        except Max7310Error:
            pass

    def configure(self):
        """Configure the MAX7310 for the OPD node."""

        inputs = 1 << self._NOT_FAULT_PIN
        self._max7310.configure(0, 0, inputs, self._TIMEOUT_CONFIG)
        if self._mock:
            self._max7310._mock_input_set(self._NOT_FAULT_PIN)  # pylint: disable=W0212
        self._status = OpdNodeState.DISABLED

    def probe(self, reset: bool = False) -> bool:
        """
        Probe the OPD for a node (see if it is there). Will automatically call configure the
        MAX7310, if found.

        Parameters
        ----------
        reset: bool
            Optional flag to reset the MAX7310, if found.

        Returns
        -------
        bool
            If the node was found.
        """

        logger.debug(f"probing OPD node {self.name} (0x{self.addr:02X})")

        if self._status == OpdNodeState.DEAD:
            return False  # node is dead, no reason to probe

        try:
            if self._max7310.is_valid:
                if self._status == OpdNodeState.NOT_FOUND:
                    logger.info(f"OPD node {self.name} (0x{self.addr:02X}) was found")
                    self.configure()

                if reset:
                    self._max7310.reset()
                    self.configure()

                self._status = OpdNodeState.DISABLED
            else:
                if self._status != OpdNodeState.NOT_FOUND:
                    logger.info(f"OPD node {self.name} (0x{self.addr:02X}) was lost")
                    self._status = OpdNodeState.NOT_FOUND
        except Max7310Error as e:
            logger.error(f"MAX7310 error: {e}")
            logger.debug(f"OPD node {self.name} (0x{self.addr:02X}) was not found")
            self._status = OpdNodeState.NOT_FOUND

        return self._status != OpdNodeState.NOT_FOUND

    def enable(self) -> OpdNodeState:
        """
        Enable the OPD node.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        """

        logger.info(f"enabling OPD node {self.name} (0x{self.addr:02X})")

        if self._status == OpdNodeState.NOT_FOUND:
            return self._status  # cannot enable node that is NOT_FOUND

        try:
            self._max7310.output_set(self._ENABLE_PIN)
            self._status = OpdNodeState.ENABLED
        except Max7310Error:
            self._status = OpdNodeState.FAULT

        return self._status

    def disable(self) -> OpdNodeState:
        """
        Disable the OPD node.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        """

        logger.info(f"disabling OPD node {self.name} (0x{self.addr:02X})")

        try:
            self._status = OpdNodeState.DISABLED
            self._max7310.output_clear(self._ENABLE_PIN)
        except Max7310Error:
            self._status = OpdNodeState.FAULT

        return self._status

    def reset(self, attempts: int = 3) -> OpdNodeState:
        """
        Reset a node on the OPD (disable and then re-enable it) Will try up to reset up
        to X times.

        Parameters
        ----------
        attempts: int
            The times to attempt to reset.
        """

        for i in range(attempts):
            logger.debug(f"resetting OPD node {self.name} (0x{self.addr:02X}), try {i + 1}")
            try:
                self._max7310.output_set(self._CB_RESET_PIN)
                sleep(self._RESET_DELAY_S)
                self._max7310.output_clear(self._CB_RESET_PIN)

                if self._mock:
                    self._max7310._mock_input_set(self._NOT_FAULT_PIN)  # pylint: disable=W0212

                if self.fault:
                    self._status = OpdNodeState.FAULT
                else:
                    self._status = OpdNodeState.ENABLED
                    break
            except Max7310Error:
                continue

        return self._status

    @property
    def name(self) -> str:
        """int: Unique name."""

        return self._name

    @property
    def addr(self) -> int:
        """int: Unique address."""

        return self._addr

    @property
    def status(self) -> OpdNodeState:
        """OpdNodeState: Status of the OPD node."""

        return self._status

    @property
    def is_enabled(self) -> bool:
        """bool: The node is enabled."""

        try:
            enabled = self._max7310.output_status(self._ENABLE_PIN)
        except Max7310Error as e:
            if self._status != OpdNodeState.NOT_FOUND:
                self._status = OpdNodeState.FAULT
            raise OpdError(e) from e

        return enabled

    @property
    def fault(self) -> bool:
        """bool: The OPD fault pin has tripped."""

        try:
            fault = not self._max7310.input_status(self._NOT_FAULT_PIN)
        except Max7310Error as e:
            if self._status != OpdNodeState.NOT_FOUND:
                self._status = OpdNodeState.FAULT
            raise OpdError(e) from e

        return fault


class OpdStm32Node(OpdNode):
    """A STM32-based OPD Node"""

    _I2C_SCL_PIN = 0  # i2c bootloader
    _I2C_SDA_PIN = 1  # i2c bootloader
    _BOOT_PIN = 5  # bootloader
    _UART_PIN = 7  # connect to C3 UART

    def enable(self, bootloader_mode: bool = False) -> OpdNodeState:
        """
        Enable the OPD node.

        Parameters
        ----------
        bootloader_mode: bool
            Boot into bootloader mode.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        """

        try:
            if bootloader_mode:
                self._max7310.output_set(self._BOOT_PIN)
            else:
                self._max7310.output_clear(self._BOOT_PIN)
        except Max7310Error:
            self._status = OpdNodeState.FAULT
            return self._status

        return super().enable()

    def configure(self):
        """Configure the MAX7310 for the OPD node."""

        inputs = 1 << self._I2C_SCL_PIN | 1 << self._I2C_SDA_PIN | 1 << self._NOT_FAULT_PIN
        self._max7310.configure(0, 0, inputs, self._TIMEOUT_CONFIG)
        if self._mock:
            self._max7310._mock_input_set(self._NOT_FAULT_PIN)  # pylint: disable=W0212
        self._status = OpdNodeState.DISABLED

    def enable_uart(self):
        """Connect the node the C3's UART"""

        self._max7310.output_set(self._UART_PIN)

    def disable_uart(self):
        """Disconnect the node from the C3's UART"""

        self._max7310.output_clear(self._UART_PIN)

    @property
    def is_uart_enabled(self) -> bool:
        """bool: Check if the UART pin is connected"""

        return self._max7310.output_status(self._UART_PIN)


class OpdOctavoNode(OpdNode):
    """A Octavo A8-based OPD Node"""

    _BOOT_PIN = 5  # boot select; eMMC or SD card
    _UART_PIN = 7  # connect to C3 UART

    def enable(self, boot_select: bool = True) -> OpdNodeState:
        """
        Enable the OPD node.

        Parameters
        ----------
        boot_select: bool
            Boot of of eMMC or SD card. Not implemented yet.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        """

        try:
            if boot_select:
                self._max7310.output_set(self._BOOT_PIN)
            else:
                self._max7310.output_clear(self._BOOT_PIN)
        except Max7310Error:
            self._status = OpdNodeState.FAULT
            return self._status

        return super().enable()

    def enable_uart(self):
        """Connect the node the C3's UART"""

        self._max7310.output_set(self._UART_PIN)

    def disable_uart(self):
        """Disconnect the node the C3's UART"""

        self._max7310.output_clear(self._UART_PIN)

    @property
    def is_uart_enabled(self) -> bool:
        """bool: Check if the UART pin is connected"""

        return self._max7310.output_status(self._UART_PIN)


class OpdState(IntEnum):
    """OPD subsystem states."""

    DISABLED = 0x0
    """OPD subsystem is off."""
    ENABLED = 0x1
    """OPD subsystem is on (no faults)."""
    FAULT = 0x2
    """OPD subsystem is on and has one or more faults."""
    DEAD = 0x3
    """OPD subsystem is consider dead (too many faults in a row)."""


class Opd:
    """OreSat Power Domain."""

    # values for getting opd current value from ADC pin
    _R_SET = 23_700  # ohms
    _MAX982L_CUR_RATIO = 965  # curret ratio

    def __init__(
        self,
        not_enable_pin: str,
        not_fault_pin: str,
        current_pin: int,
        mock: bool = False,
    ):
        """
        Parameters
        ----------
        not_enable_pin: str
            Output pin that enables/disables the OPD subsystem.
        not_fault_pin: str
            Input pin for faults.
        current_pin: int
            ADC pin number to get OPD current.
        mock: bool
            Mock the OPD subsystem.
        """

        self._not_enable_pin = Gpio(not_enable_pin, mock)
        self._not_fault_pin = Gpio(not_fault_pin, mock)
        self._not_fault_pin._mock_value = 1  # fix default for mocking
        self._adc = Adc(current_pin, mock)
        self._not_enable_pin.high()  # make sure OPD disable initially

        self._nodes = {}  # type: ignore
        self._status = OpdState.DISABLED
        self.stop_loop = True
        self._resets = 0

    def __getitem__(self, name: str) -> OpdNode:
        return self._nodes[name]

    def __setitem__(self, name: str, node: OpdNode):
        self._nodes[name] = node

    def __iter__(self) -> OpdNode:
        for node in self._nodes.values():
            yield node

    def enable(self):
        """Enable the OPD subsystem, will also do a scan."""

        if self._status == OpdState.DEAD:
            raise OpdError("OPD subsystem is consider dead")
        if self._status in [OpdState.ENABLED, OpdState.FAULT]:
            return  # already enabled

        logger.info("starting OPD subsystem")
        self._not_enable_pin.low()
        self._status = OpdState.ENABLED

        self.scan(True)

    def disable(self):
        """Disable the OPD subsystem."""

        logger.info("stopping OPD subsystem")

        for node in self:
            if node.status != OpdNodeState.NOT_FOUND:
                node.disable()

        self._not_enable_pin.high()
        self._status = OpdState.DISABLED
        self._resets = 0

    def reset(self, tries: int = 3, disable_delay: float = 10):
        """
        Restart the OPD subsystem with a delay between stop and start.

        Parameters
        ----------
        tries: int
            Number of tries in a row to try to reset the OPD subsystem.
        disable_delay: float
            Number of seconds betwen try to disabling and enabling the subsystem to reset it.
        """

        reset = 0
        while self._status == OpdState.FAULT and reset < tries:
            reset += 1
            logger.info(f"resetting OPD subsystem, try {reset}")
            self.disable()
            sleep(disable_delay)
            self.enable()
            if self.has_fault:
                self._status = OpdState.FAULT

        if self._status == OpdState.FAULT:
            logger.critical(
                f"OPD monitor failed fix subsystem after {tries} "
                "resets, subsystem is now consider dead"
            )
            self.disable()
            self._status = OpdState.DEAD

    def scan(self, reset: bool = False) -> int:
        """
        Scan / probe for all nodes. This will turn on all battery cards found.

        Parameters
        ----------
        reset: bool
            Optional flag to reset any node that is found.

        Returns
        -------
        int
            The number of nodes found.
        """

        count = 0
        for node in self._nodes.values():
            if node.probe(reset):
                count += 1

        return count

    @property
    def has_fault(self) -> bool:
        """bool: OPD circuit has a fault."""

        return not self._not_fault_pin.is_high

    @property
    def current(self) -> int:
        """int: OPD current in milliamps."""

        return int(self._adc.value * self._MAX982L_CUR_RATIO / self._R_SET * 1000)

    @property
    def status(self) -> OpdState:
        """OpdState: OPD subsystem status."""

        return self._status
