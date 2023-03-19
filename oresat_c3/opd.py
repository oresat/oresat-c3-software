'''
Everything todo with the OPD (OreSat Power Domain) functionality.
'''

from enum import IntEnum
from time import sleep

from olaf import logger


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


class Opd:
    '''
    OreSat Power Domain.
    '''

    def __init__(self, mock: bool = False):

        if not mock:
            raise NotImplementedError
        else:
            logger.warning('mocking OPD')

        self.enable_system()

    def enable_system(self):
        '''Enable the OPD subsystem.'''

        logger.info('enabling OPD subsystem')
        self._nodes = {i: False for i in OpdNode}  # reset
        self._enabled = True

    def disable_system(self):
        '''Disable the OPD subsystem.'''

        logger.info('disabling OPD subsystem')
        self._enabled = False

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

    def reset_node(self, node: OpdNode):
        '''
        Reset a node on the OPD (disable and then re-enable it).

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        '''

        self.disable(node)
        sleep(0.01)
        self.enable(node)

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

        if restart:
            self.reset_node(node)

        return True

    def node_status(self, node: OpdNode) -> bool:
        '''
        Get the status of a node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.

        Returns
        -------
        bool
            The power status of a node.
        '''

        logger.debug(f'getting the status of OPD node {node.name}')
        self._is_valid_and_enabled(node)
        return self._nodes[node]

    def enable_node(self, node: OpdNode):
        '''
        Enable an OPD node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to enable.
        '''

        logger.info(f'enabling OPD node {node.name}')
        self._is_valid_and_enabled(node)
        self._nodes[node] = True

    def disable_node(self, node: OpdNode):
        '''
        Disable an OPD node.

        Parameters
        ----------
        node: OpdNode
            The OPD node id to disable.
        '''

        logger.info(f'disabling OPD node {node.name}')
        self._is_valid_and_enabled(node)
        self._nodes[node] = False
