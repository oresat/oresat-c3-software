'''
Everything todo with the OPD (OreSat Power Domain) functionality.

Every card, other than the solar cards, has a MAX7310 that can be used to turn the card or off.
'''

from enum import IntEnum
from time import sleep

from olaf import logger, GPIO

from ..drivers.max7310 import Max7310, Max7310Error


class OpdError(Exception):
    '''Error with the `Opd`'''


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


class OpdNodeState(IntEnum):
    '''OPD node states'''

    OFF = 0
    ON = 1
    NOT_FOUND = 0xFF


class OpdPin(IntEnum):
    '''
    The MAX7310 pins uses on OPD.

    MAX7310 pin 7 is not used.
    '''

    SCL = 0
    SDA = 1
    FAULT = 2
    EN = 3
    CB_RESET = 4
    BOOT0 = 5
    LINUX_BOOT = 6


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
            Pin that enable the OPD system.
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

        logger.info('resetping OPD subsystem')

        self._gpio.high()

        self._last_valid = {i: False for i in list(OpdNode)}

    @property
    def is_system_enabled(self) -> bool:
        '''bool: OPD is enabled or not.'''

        return not self._gpio.is_high

    def _is_valid_and_enabled(self, node):
        '''
        Quick helper function that will raise an OpdError if the node does not exist or if the OPD
        system is not enabled
        '''

        if not self._gpio.is_high:
            raise OpdError('OPD system is not enabled')
        if node not in OpdNode:
            raise OpdError(f'invalid OPD node {node}')

    def probe_node(self, node: OpdNode, restart: bool) -> bool:
        '''
        Probe the OPD for a node (see if it is there).

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        restart: bool
            Restart the node, if found.

        Returns
        -------
        bool
            If the node was found.
        '''

        logger.info(f'probing OPD node {node.name} (0x{node.value:02X})')

        try:
            self._is_valid_and_enabled(node)
            if self._nodes[node.value].is_valid:
                if not self._last_valid[node.value]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was found')
                self._last_valid[node.value] = True

                if restart:
                    self._nodes[node.value].reset()
                    self._nodes[node.value].configure(self._OUT_CONFIG, self._PI_CONFIG,
                                                      self._CONF_CONFIG, self._TIMEOUT_CONFIG)
            else:
                if self._last_valid[node.value]:
                    logger.info(f'OPD node {node.name} (0x{node.value:02X}) was lost')
                self._last_valid[node.value] = False

                # no response, ensure address is stopped (reset max7310)
                self._nodes[node.value].reset()
        except Max7310Error:
            logger.debug(f'OPD node {node.name} (0x{node.value:02X}) was not found')
            self._last_valid[node.value] = False

        return self._last_valid[node.value]

    def scan(self, restart: bool):
        '''
        Scan / probe for all nodes.

        Parameters
        ----------
        restart: bool
            Restart a node, if found.
        '''

        for node in list(OpdNode):
            self.probe_node(node, restart)

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

        self._nodes[node.value].set_pin(OpdPin.EN)

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

        self._nodes[node.value].clear_pin(OpdPin.EN)

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

        self._nodes[node.value].set_pin(OpdPin.CB_RESET)
        sleep(self._RESET_DELAY_S)
        self._nodes[node.value].clear_pin(OpdPin.CB_RESET)

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
            value = OpdNodeState(int(self._nodes[node.value].pin_status(OpdPin.EN)))
        except Max7310Error:
            value = OpdNodeState.NOT_FOUND

        return value
