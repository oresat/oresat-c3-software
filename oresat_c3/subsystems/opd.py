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
    NOT_FOUND = 0xFF
    '''OPD node is not found'''


class OpdPin(IntEnum):
    '''The MAX7310 pins uses on the OPD.'''

    SCL = 0
    '''Input: The I2C SCL'''
    SDA = 1
    '''Input: The I2C SDA'''
    FAULT = 2
    '''Input: If this is high there is a error. Hopefully the CB_RESET output can be used to clear
    the error.'''
    ENABLE = 3
    '''Output: Enable (high) or disable (low) the node on the OPD.'''
    CB_RESET = 4
    '''Output: Can be used to try to clear the fault.'''
    BOOT0 = 5
    '''Output: ?'''
    LINUX_BOOT = 6
    '''Output: Only used by Linux cards'''
    TBD = 7
    '''Output: ?'''


class Opd:
    '''OreSat Power Domain.'''

    _RESET_DELAY_S = 0.25
    _OUT_CONFIG = 1 << OpdPin.LINUX_BOOT.value
    _PI_CONFIG = 1 << OpdPin.FAULT.value
    _CONF_CONFIG = 1 << OpdPin.SCL.value | 1 << OpdPin.SDA.value | 1 << OpdPin.FAULT.value
    _TIMEOUT_CONFIG = 1

    def __init__(self, enable_pin: int, bus: int, mock: bool = False):
        '''
        Parameters
        ----------
        enable_pin: int
            Pin that enable the OPD subsystem.
        bus: int
            The I2C bus.
        mock: bol
            Mock the OPD subsystem.
        '''

        self._gpio = GPIO(enable_pin, mock)
        self._nodes = {i: Max7310(bus, i, mock) for i in list(OpdNode)}
        self._last_valid = {i: False for i in list(OpdNode)}

    def start(self):
        '''Start the OPD subsystem, will also do a scan.'''

        logger.info('starting OPD subsystem')

        self._gpio.low()

        self.scan(True)

    def stop(self):
        '''Stop the OPD subsystem.'''

        logger.info('stopping OPD subsystem')

        self._gpio.high()

        self._last_valid = {i: False for i in list(OpdNode)}

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

    def probe_node(self, node: OpdNode, restart: bool) -> bool:
        '''
        Probe the OPD for a node (see if it is there). Will automatically call configure the
        MAX7310, if found.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        restart: bool
            Reset the MAX7310, if found.

        Returns
        -------
        bool
            If the node was found.
        '''

        logger.info(f'probing OPD node {node.name} (0x{node.value:02X})')

        try:
            self._is_valid_and_enabled(node)
            if self._nodes[node].is_valid:
                if not self._last_valid[node]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was found')
                    self._nodes[node].configure(self._OUT_CONFIG, self._PI_CONFIG,
                                                self._CONF_CONFIG, self._TIMEOUT_CONFIG)

                if restart:
                    self._nodes[node].reset()
                    self._nodes[node].configure(self._OUT_CONFIG, self._PI_CONFIG,
                                                self._CONF_CONFIG, self._TIMEOUT_CONFIG)

                self._last_valid[node] = True
            else:
                if self._last_valid[node]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was lost')
                self._last_valid[node] = False
        except Max7310Error:
            logger.debug(f'OPD node {node.name} (0x{node.value:02X}) was not found')
            self._last_valid[node] = False

        return self._last_valid[node]

    def scan(self, restart: bool):
        '''
        Scan / probe for all nodes.

        Parameters
        ----------
        restart: bool
            Restart a node, if found.

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

        self._nodes[node].set_pin(OpdPin.ENABLE)

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

        self._nodes[node].clear_pin(OpdPin.ENABLE)

    def reset(self, node: OpdNode):
        '''
        Reset a node on the OPD (disable and then re-enable it).

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
            self._nodes[node].set_pin(OpdPin.CB_RESET)
            sleep(self._RESET_DELAY_S)
            self._nodes[node].clear_pin(OpdPin.CB_RESET)

            if self._nodes[node].pin_status(OpdPin.FAULT):
                reset = True
                break

        if not reset:
            raise OpdError(f'OPD node {node.name} (0x{node.value:02X}) failed to reset 3 times in '
                           'a row')

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

        try:
            if self._nodes[node].pin_status(OpdPin.FAULT):
                value = OpdNodeState.ERROR
            else:
                value = OpdNodeState(int(self._nodes[node].pin_status(OpdPin.ENABLE)))
        except Max7310Error:
            value = OpdNodeState.NOT_FOUND

        return value
