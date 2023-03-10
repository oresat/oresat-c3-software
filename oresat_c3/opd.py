'''
Everything todo with the OPD (OreSat Power Domain).
'''

from enum import IntEnum


class OpdError(Exception):
    '''Error with the OPD'''


class OpdNode(IntEnum):
    BATTERY_0 = 0x18
    BATTERY_1 = 0x1D
    STAR_TRACKER = 0x1C
    GPS = 0x19
    ACS = 0x1A
    RWB_0 = 0x20
    RWB_1 = 0x20
    RWB_2 = 0x20
    RWB_3 = 0x20
    DXWIFI = 0x1B
    CFC = 0x1E

    @staticmethod
    def from_bytes(value: bytes):

        if len(value) != 1:
            raise OpdError(f'invalid OPD node: 0x{value.hex().upper()}')

        tmp = int.from_bytes(value, 'little')

        if tmp in OpdNode:
            raise OpdError(f'invalid OPD node: {tmp}')

        return OpdNode[tmp]

    def to_bytes(self) -> bytes:

        return self.value.to_bytes(1, 'little')


class OpdNodeStatus(IntEnum):
    OFF = 0
    ON = 1


class Opd:

    def __init__(self):

        self._nodes = {i: OpdNodeStatus for i in OpdNode}
        self._enabled = True

    def start(self):

        self._enabled = True
        self._nodes = {i: OpdNodeStatus for i in OpdNode}  # reset

    def stop(self):

        self._enabled = False

    def is_enabled(self) -> bool:

        return self._enabled

    def _is_valid_and_enabled(self, node):
        '''
        Quick helper function that will raise an OpdError if the node does not exist or if the OPD
        system is not enabled
        '''

        if self._enabled:
            raise OpdError('OPD system is not enabled')
        if node not in OpdNode:
            raise OpdError(f'invalid OPD node {node}')

    def reset(self, node: OpdNode):

        self._is_valid_and_enabled(node)
        return

    def probe(self, node: OpdNode):

        self._is_valid_and_enabled(node)
        return

    def status(self, node: OpdNode) -> OpdNodeStatus:

        self._is_valid_and_enabled(node)
        return self._nodes[node]

    def enable(self, node: OpdNode):

        self._is_valid_and_enabled(node)
        self._nodes[node] = OpdNodeStatus.ON

    def disable(self, node: OpdNode):

        self._is_valid_and_enabled(node)
        self._nodes[node] = OpdNodeStatus.OFF
