'''
Everything todo with the OPD (OreSat Power Domain) functionality.

Every card, other than the solar cards, has a MAX7310 that can be used to turn the card or off.
'''

from enum import IntEnum
from time import sleep

from olaf import logger, GPIO

from ..drivers.max7310 import Max7310, Max7310Error


class OpdError(Exception):
    '''Error with :py:class:`Opd`'''


class OpdNode(IntEnum):
    '''I2C addresses for all cards on the OPD'''

    BATTERY_0 = 0x18
    GPS = 0x19
    ACS = 0x1A
    DXWIFI = 0x1B
    STAR_TRACKER_0 = 0x1C
    BATTERY_1 = 0x1D
    CFC = 0x1E
    CFC_SENSOR = 0x1F
    RW_0 = 0x20
    RW_1 = 0x21
    RW_2 = 0x22
    RW_3 = 0x23

    @staticmethod
    def from_bytes(value: bytes):
        return OpdNode(int.from_bytes(value, 'little'))

    @property
    def is_linux_card(self) -> bool:
        '''bool: Flag for if the OPD node is a Linux card.'''

        if self in [OpdNode.GPS, OpdNode.DXWIFI, OpdNode.STAR_TRACKER_0, OpdNode.CFC]:
            return True
        return False


class OpdNodeState(IntEnum):
    '''OPD node states'''

    OFF = 0
    '''OPD Node is off'''
    ON = 1
    '''OPD Node is on'''
    ERROR = 2
    '''Fault input is set for OPD node'''
    DEAD = 3
    '''The node is dead'''
    NOT_FOUND = 0xFF
    '''OPD node is not found'''


class OpdStm32Pin(IntEnum):
    '''The MAX7310 pins uses on the OPD for STM32s.'''

    SCL = 0
    '''Input: The I2C SCL. Allows for I2C bootloader for the STM32s.'''
    SDA = 1
    '''Input: The I2C SDA. Allows for I2C bootloader for the STM32s.'''
    NOT_FAULT = 2
    '''Input: If this is low there the circut breaker has tripped.
    Hopefully the CB_RESET output can be used to clear the error.'''
    ENABLE = 3
    '''Output: Enable (high) or disable (low) the node on the OPD.'''
    CB_RESET = 4
    '''Output: Circuit breaker reset. Can be used to try to clear the
    fault. If it goes high it reset the circut breakers, must be high
    for several milliseconds.'''
    BOOT = 5
    '''Output: If boot high, the STM32 will go into boot loader mode.'''
    TEST_POINT = 6
    '''Output: Just a test point, set low.'''
    UART_ENABLE = 7
    '''Output: UART connect, when high it will connect the card to C3 UART.'''


class OpdOctavoPin(IntEnum):
    '''The MAX7310 pins uses on the OPD for Octavo A8s.'''

    TEST_POINT0 = 0
    '''Output: Just a test point, set low.'''
    TEST_POINT1 = 0
    '''Output: Just a test point, set low.'''
    NOT_FAULT = 2
    '''Input: If this is low there the circut breaker has tripped.
    Hopefully the CB_RESET output can be used to clear the error.'''
    ENABLE = 3
    '''Output: Enable (high) or disable (low) the node on the OPD.'''
    CB_RESET = 4
    '''Output: Circuit breaker reset. Can be used to try to clear the
    fault. If it goes high it reset the circut breakers, must be high
    for several milliseconds.'''
    BOOT = 5
    '''Output: The boot select pin; eMMC or SD card. (not yet implamented)'''
    TEST_POINT6 = 6
    '''Output: Just a test point, set low.'''
    UART_ENABLE = 7
    '''Output: UART connect, when high it will connect the card to C3 UART.'''


class OpdCfcSensorPin(IntEnum):
    '''The MAX7310 pins uses on the OPD for the CFC sensor card.'''

    TEST_POINT0 = 0
    '''Output: Just a test point, set low.'''
    TEST_POINT1 = 0
    '''Output: Just a test point, set low.'''
    NOT_FAULT = 2
    '''Input: If this is low there the circut breaker has tripped.
    Hopefully the CB_RESET output can be used to clear the error.'''
    ENABLE = 3
    '''Output: Enable (high) or disable (low) the node on the OPD.'''
    CB_RESET = 4
    '''Output: Circuit breaker reset. Can be used to try to clear the
    fault. If it goes high it reset the circut breakers, must be high
    for several milliseconds.'''
    TEST_POINT5 = 5
    '''Output: Just a test point, set low.'''
    TEST_POINT = 6
    '''Output: Just a test point, set low.'''
    TEST_POINT7 = 7
    '''Output: Just a test point, set low.'''


class Opd:
    '''OreSat Power Domain.'''

    _NODE_RESET_DELAY_S = 0.25
    _SYS_RESET_DELAY_S = 10

    _STM32_CONFIG = 1 << OpdStm32Pin.SCL.value | 1 << OpdStm32Pin.SDA.value \
        | 1 << OpdStm32Pin.NOT_FAULT.value
    _OCTAVO_CONFIG = 1 << OpdStm32Pin.NOT_FAULT.value
    _CFC_SENSOR_CONFIG = 1 << OpdStm32Pin.NOT_FAULT.value
    _TIMEOUT_CONFIG = 1

    # these are consistence
    _ENABLE_PIN = OpdStm32Pin.ENABLE.value
    _NOT_FAULT_PIN = OpdStm32Pin.ENABLE.value
    _CB_RESET_PIN = OpdStm32Pin.ENABLE.value

    def __init__(self, enable_pin: int, bus: int, mock: bool = False):
        '''
        Parameters
        ----------
        enable_pin: int
            Pin that enable the OPD subsystem.
        bus: int
            The I2C bus.
        mock: bool
            Mock the OPD subsystem.
        '''

        self._gpio = GPIO(enable_pin, mock)
        self._nodes = {i: Max7310(bus, i, mock) for i in list(OpdNode)}
        self._last_probe = {i: False for i in list(OpdNode)}
        self._status = {i: OpdNodeState.OFF for i in list(OpdNode)}

    def start(self):
        '''Start the OPD subsystem, will also do a scan.'''

        logger.info('starting OPD subsystem')

        self._gpio.low()

        self.scan(True)

    def stop(self):
        '''Stop the OPD subsystem.'''

        logger.info('stopping OPD subsystem')

        self._gpio.high()

        for i in self._status:
            if self._status[i] == OpdNodeState.ON:
                self._status[i] = OpdNodeState.OFF

        self._last_probe = {i: False for i in list(OpdNode)}

    def restart(self):
        '''Restart the OPD subsystem with a delay between stop and start.'''

        self.stop()
        sleep(self._SYS_RESET_DELAY_S)
        self.start()

    @property
    def is_system_enabled(self) -> bool:
        '''bool: OPD is enabled or not.'''

        return not self._gpio.is_high

    def _is_valid_and_enabled(self, node):
        '''
        Quick helper function that will raise an OpdError if the node does not exist or if the OPD
        subsystem is not enabled
        '''

        if self._gpio.is_high:
            raise OpdError('OPD subsystem is not enabled')
        if node not in OpdNode:
            raise OpdError(f'invalid OPD node {node}')

    def _config_node(self, node: OpdNode):
        '''Handle GPIO configration for different cards'''

        if node == OpdNode.CFC_SENSOR:
            self._nodes[node].configure(0, 0, self._CFC_SENSOR_CONFIG, self._TIMEOUT_CONFIG)
        elif node in node.is_linux_card:
            self._nodes[node].configure(0, 0, self._OCTAVO_CONFIG, self._TIMEOUT_CONFIG)
        else:
            self._nodes[node].configure(0, 0, self._STM32_CONFIG, self._TIMEOUT_CONFIG)

    def probe_node(self, node: OpdNode, restart: bool = False) -> bool:
        '''
        Probe the OPD for a node (see if it is there). Will automatically call configure the
        MAX7310, if found.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        restart: bool
            Optional flag to reset the MAX7310, if found.

        Returns
        -------
        bool
            If the node was found.
        '''

        logger.info(f'probing OPD node {node.name} (0x{node.value:02X})')

        if self._status[node] == OpdNodeState.DEAD:
            return False  # node is dead, no reason to probe

        try:
            self._is_valid_and_enabled(node)
            if self._nodes[node].is_valid:
                if not self._last_probe[node]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was found')
                    self._config_node(node)

                if restart:
                    self._nodes[node].reset()
                    self._config_node(node)

                self._last_probe[node] = True
                self._status[node] = OpdNodeState.OFF
            else:
                if self._last_probe[node]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was lost')
                    self._status[node] = OpdNodeState.NOT_FOUND
                self._last_probe[node] = False
        except Max7310Error:
            logger.debug(f'OPD node {node.name} (0x{node.value:02X}) was not found')
            self._status[node] = OpdNodeState.NOT_FOUND
            self._last_probe[node] = False

        return self._last_probe[node]

    def scan(self, restart: bool = False):
        '''
        Scan / probe for all nodes.

        Parameters
        ----------
        restart: bool
            Optional flag to restart any node that is found.

        Returns
        -------
        int
            The number of nodes found.
        '''

        count = 0

        for node in list(OpdNode):
            if self.probe_node(node, restart):
                count += 1

        return count

    def enable(self, node: OpdNode):
        '''
        Enable an OPD node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        '''

        logger.info(f'enabling OPD node {node.name} (0x{node.value:02X})')
        self._is_valid_and_enabled(node)

        self._nodes[node].set_pin(self._ENABLE_PIN)
        self._status[node] = OpdNodeState.ON

    def disable(self, node: OpdNode):
        '''
        Disable an OPD node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to disable.
        '''

        logger.info(f'disabling OPD node {node.name} (0x{node.value:02X})')
        self._is_valid_and_enabled(node)

        self._nodes[node].clear_pin(self._ENABLE_PIN)
        self._status[node] = OpdNodeState.OFF

    def reset(self, node: OpdNode):
        '''
        Reset a node on the OPD (disable and then re-enable it) Will try up to reset up
        to 3 times.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        '''

        logger.info(f'reseting OPD node {node.name} (0x{node.value:02X})')
        self._is_valid_and_enabled(node)

        reset = False

        for i in range(3):
            logger.info(f'reseting OPD node {node.name} (0x{node.value:02X}) try {i + 1}')
            try:
                self._nodes[node].set_pin(self._CB_RESET_PIN)
                sleep(self._NODE_RESET_DELAY_S)
                self._nodes[node].clear_pin(self._CB_RESET_PIN)

                if self._nodes[node].pin_status(self._NOT_FAULT_PIN):
                    reset = True
                    break
            except Max7310Error:
                continue

        if not reset:
            self._status[node] = OpdNodeState.DEAD
            logger.critical(f'OPD node {node.name} (0x{node.value:02X}) failed to reset 3 times '
                            'in a row, is now consider dead')

    def status(self, node: OpdNode) -> OpdNodeState:
        '''
        Get the Status of a node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.

        Returns
        -------
        OpdNodeState
            The status of the OPD node.
        '''

        if self.fault(node):
            self._status[node] = OpdNodeState.ERROR

        return self._status[node]

    def fault(self, node: OpdNode) -> bool:
        '''
        Get the Status of a node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.

        Returns
        -------
        bool
            If circut breaker is tripped.
        '''

        return not bool(self._nodes[node].input_port & 1 < self._NOT_FAULT_PIN)
