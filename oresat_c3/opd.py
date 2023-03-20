'''
Everything todo with the OPD (OreSat Power Domain) functionality.
'''

from enum import IntEnum
from time import sleep
from dataclasses import dataclass

from olaf import logger

from .drivers.max7310 import Max7310, Max7310Status, Max7310Config


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
    SCL = 0
    SDA = 1
    FAULT = 2
    EN = 3
    CB_RESET = 4
    BOOT0 = 5
    LINUX_BOOT = 6
    PIN7 = 7


@dataclass
class OpdNodeStatus:
    max_status: Max7310Status = Max7310Status()
    config: Max7310Config = Max7310Config(
        odr=1 << OpdPin.LINUX_BOOT.value,
        pol=1 << OpdPin.FAULT.value,
        iomode=1 << OpdPin.SCL.value | 1 << OpdPin.SDA.value | 1 << OpdPin.FAULT.value,
        timeout=1
    )
    valid: bool = False
    enabled: bool = False


class Opd:
    '''
    OreSat Power Domain.
    '''

    _RESET_DELAY_S = 0.25

    def __init__(self, mock: bool = False):

        if not mock:
            self._max7310 = Max7310(1)
        else:
            self._max7310 = None
            logger.warning('mocking OPD')

        self._statuses = {i: OpdNodeStatus() for i in OpdNode}
        self._enabled = True

    def start(self):
        '''Enable the OPD subsystem.'''

        logger.info('starting OPD subsystem')
        self._enabled = True
        self.scan(True)

    def stop(self):
        '''Disable the OPD subsystem.'''

        logger.info('stopping OPD subsystem')
        self._enabled = False

        for node in list(OpdNode):
            if self._max7310:
                self._max7310.stop(node.value)
            self._statuses[node].valid = False
            self._statuses[node].enabled = False

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
        response = True

        if response:
            status = self._statuses[node]
            if self._max7310 and (not status.valid or restart):
                self._max7310.stop(node.value)
                self._max7310.start(node.value, status.config)
            self._statuses[node].valid = True
        else:
            if self._max7310:
                self._max7310.stop(node.value)
            self._statuses[node].valid = False

        return self._statuses[node].valid

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

    def node_status(self, node: OpdNode) -> OpdNodeStatus:
        '''
        Get the status of a node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.

        Returns
        -------
        OpdNodeStatus
            The status of a node.
        '''

        logger.debug(f'getting the status of OPD node {node.name}')
        self._is_valid_and_enabled(node)

        if self._max7310:
            max_status = self._max7310.status(node.value)
        else:
            max_status = Max7310Status()

        self._statuses[node].max_status = max_status

        return self._statuses[node]

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

        if self._max7310:
            self._max7310.set_pin(node.value, OpdPin.EN)

        self._statuses[node].enabled = True

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

        if self._max7310:
            self._max7310.clear_pin(node.value, OpdPin.EN)

        self._statuses[node].enabled = False

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

        if self._max7310:
            self._max7310.set_pin(node.value, OpdPin.CB_RESET)

        self._statuses[node].enabled = False

        sleep(self._RESET_DELAY_S)

        if self._max7310:
            self._max7310.clear_pin(node.value, OpdPin.CB_RESET)

        self._statuses[node].enabled = True
