'''
Everything todo with the OPD (OreSat Power Domain) functionality.

Every card, other than the solar cards, has a MAX7310 that can be used to turn the card or off.
'''

from enum import IntEnum
from time import sleep

from olaf import logger

from .drivers.max7310 import Max7310


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
        '''Convert `bytes` value to `OpdNode` object'''

        if len(value) != 1:
            raise OpdError(f'invalid OPD node: 0x{value.hex().upper()}')

        tmp = int.from_bytes(value, 'little')

        if tmp in OpdNode:
            raise OpdError(f'invalid OPD node: {tmp}')

        return OpdNode[tmp]

    def to_bytes(self) -> bytes:
        '''Convert object to `bytes` value'''

        return self.value.to_bytes(1, 'little')


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
    _OPR_CONFIG = 1 << OpdPin.LINUX_BOOT.value,
    _PIR_CONFIG = 1 << OpdPin.FAULT.value,
    _CR_CONFIG = 1 << OpdPin.SCL.value | 1 << OpdPin.SDA.value | 1 << OpdPin.FAULT.value,
    _TIMEOUT_CONFIG = 1

    def __init__(self, mock: bool = False):

        self._nodes = {i: Max7310(1, i, mock) for i in list(OpdNode)}
        self._enabled = True

    def start(self):
        '''Start the OPD subsystem.'''

        logger.info('starting OPD subsystem')
        self._enabled = True
        self.scan(True)

    def stop(self):
        '''Stop the OPD subsystem.'''

        logger.info('resetping OPD subsystem')
        self._enabled = False

        for node in list(OpdNode):
            if self._nodes:
                self._nodes[node.value].reset()

    @property
    def is_system_enabled(self) -> bool:
        '''bool: OPD is enabled or not.'''

        return self._enabled

    def _is_valid_and_enabled(self, node):
        '''
        Quick helper function that will raise an OpdError if the node does not exist or if the OPD
        system is not enabled
        '''

        if not self._enabled:
            raise OpdError('OPD system is not enabled')
        if node not in OpdNode:
            raise OpdError(f'invalid OPD node {node}')

    def probe_node(self, node: OpdNode, restart: bool):
        '''
        Probe the OPD for a node (see if it is there).

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        restart: bool
            Restart the node if found.
        '''

        logger.info(f'probing OPD node {node.name}')
        self._is_valid_and_enabled(node)

        # TODO I2c mater receive ??

        if self._nodes[node.value].is_valid:
            if restart:
                self._nodes[node.value].reset()
                self._nodes[node.value].configure(self._OPR_CONFIG, self._PIR_CONFIG,
                                                  self._CR_CONFIG, self._TIMEOUT_CONFIG)
        else:
            self._nodes[node.value].reset()

    def scan(self, restart: bool):
        '''
        Scan / probe for all nodes.

        Parameters
        ----------
        restart: bool
            Restart the node if found.
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

        logger.info(f'enabling OPD node {node.name}')
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

        logger.info(f'disabling OPD node {node.name}')
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

        logger.info(f'reseting OPD node {node.name}')
        self._is_valid_and_enabled(node)

        self._nodes[node.value].set_pin(OpdPin.CB_RESET)
        sleep(self._RESET_DELAY_S)
        self._nodes[node.value].clear_pin(OpdPin.CB_RESET)
