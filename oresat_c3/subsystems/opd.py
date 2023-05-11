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


class OpdNodeId(IntEnum):
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
        return OpdNodeId(int.from_bytes(value, 'little'))

    @property
    def is_linux_card(self) -> bool:
        '''bool: Flag for if the OPD node is a Linux card.'''

        if self in [OpdNodeId.GPS, OpdNodeId.DXWIFI, OpdNodeId.STAR_TRACKER_0, OpdNodeId.CFC]:
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
    '''The MAX7310 pins uses on the OPD for STM32-based cards.'''

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
    TEST_POINT6 = 6
    '''Output: Just a test point, set to low.'''
    UART_ENABLE = 7
    '''Output: UART connect, when high it will connect the card to C3 UART.'''


class OpdOctavoPin(IntEnum):
    '''The MAX7310 pins uses on the OPD for Octavo A8-based cards.'''

    TEST_POINT0 = 0
    '''Output: Just a test point, set to low.'''
    TEST_POINT1 = 1
    '''Output: Just a test point, set to low.'''
    NOT_FAULT = 2
    '''Input: If this is low there the circut breaker has tripped.
    Hopefully the CB_RESET output can be used to clear the error.'''
    ENABLE = 3
    '''Output: Enable (high) or disable (low) the node on the OPD.'''
    CB_RESET = 4
    '''Output: Circuit breaker reset. Can be used to try to clear the
    fault. If it goes high it reset the circut breakers, must be high
    for several milliseconds.'''
    BOOT_SELECT = 5
    '''Output: The boot select pin; eMMC or SD card. (not implemented)'''
    TEST_POINT6 = 6
    '''Output: Just a test point, set to low.'''
    UART_ENABLE = 7
    '''Output: UART connect, when high it will connect the card to C3 UART.'''


class OpdCfcSensorPin(IntEnum):
    '''The MAX7310 pins uses on the OPD for the CFC sensor card.'''

    TEST_POINT0 = 0
    '''Output: Just a test point, set to low.'''
    TEST_POINT1 = 1
    '''Output: Just a test point, set to low.'''
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
    '''Output: Just a test point, set to low.'''
    TEST_POINT6 = 6
    '''Output: Just a test point, set to low.'''
    TEST_POINT7 = 7
    '''Output: Just a test point, set to low.'''


class Opd:
    '''OreSat Power Domain.'''

    _NODE_RESET_DELAY_S = 0.25
    _SYS_RESET_DELAY_S = 10

    _STM32_CONFIG = 1 << OpdStm32Pin.SCL.value | 1 << OpdStm32Pin.SDA.value \
        | 1 << OpdStm32Pin.NOT_FAULT.value
    _OCTAVO_CONFIG = 1 << OpdOctavoPin.NOT_FAULT.value
    _CFC_SENSOR_CONFIG = 1 << OpdCfcSensorPin.NOT_FAULT.value
    _TIMEOUT_CONFIG = 1

    # these are consistent between all cards
    _ENABLE_PIN = OpdStm32Pin.ENABLE.value
    _NOT_FAULT_PIN = OpdStm32Pin.NOT_FAULT.value
    _CB_RESET_PIN = OpdStm32Pin.CB_RESET.value

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
        self._nodes = {i: Max7310(bus, i, mock) for i in list(OpdNodeId)}
        self._status = {i: OpdNodeState.OFF for i in list(OpdNodeId)}
        self._dead = False

    def start(self):
        '''Start the OPD subsystem, will also do a scan.'''

        if self._dead:
            raise OpdError('OPD subsystem is consider dead')
        if self.is_subsystem_enabled:
            return  # already enabled

        logger.info('starting OPD subsystem')

        self._gpio.low()

        self.scan(True)

    def stop(self):
        '''Stop the OPD subsystem.'''

        logger.info('stopping OPD subsystem')

        self._gpio.high()

        for i in self._status:
            self._status[i] = OpdNodeState.OFF

    def restart(self):
        '''Restart the OPD subsystem with a delay between stop and start.'''

        self.stop()
        sleep(self._SYS_RESET_DELAY_S)
        self.start()

    @property
    def is_subsystem_enabled(self) -> bool:
        '''bool: OPD is enabled or not.'''

        return not self._gpio.is_high

    def _is_valid_and_sys_enabled(self, node_id: OpdNodeId):
        '''
        Quick helper function that will raise an OpdError if the node does not exist, if the OPD
        subsystem is not enabled, or if the subsystem is dead.
        '''

        if self.is_subsystem_dead:
            raise OpdError('OPD subsystem is dead')
        if self.is_subsystem_enabled:
            raise OpdError('OPD subsystem is disabled')
        if node_id not in list(OpdNodeId):
            raise OpdError(f'invalid OPD node id {node_id}')

    def _config_node(self, node_id: OpdNodeId):
        '''Handle GPIO configration for different cards'''

        if node_id == OpdNodeId.CFC_SENSOR:
            self._nodes[node_id].configure(0, 0, self._CFC_SENSOR_CONFIG, self._TIMEOUT_CONFIG)
        elif node_id in node_id.is_linux_card:
            self._nodes[node_id].configure(0, 0, self._OCTAVO_CONFIG, self._TIMEOUT_CONFIG)
        else:
            self._nodes[node_id].configure(0, 0, self._STM32_CONFIG, self._TIMEOUT_CONFIG)

    def probe(self, node_id: OpdNodeId, restart: bool = False) -> bool:
        '''
        Probe the OPD for a node (see if it is there). Will automatically call configure the
        MAX7310, if found.

        Parameters
        ----------
        node_id: OpdNodeId
            The OPD node id to enable.
        restart: bool
            Optional flag to reset the MAX7310, if found.

        Returns
        -------
        bool
            If the node was found.
        '''

        logger.info(f'probing OPD node {node_id.name} (0x{node_id.value:02X})')

        if self._status[node_id] == OpdNodeState.DEAD:
            return False  # node is dead, no reason to probe

        try:
            self._is_valid_and_sys_enabled(node_id)
            if self._nodes[node_id].is_valid:
                if self._status[node_id] == OpdNodeState.NOT_FOUND:
                    logger.info(f'OPD node {node_id.name} (0x{node_id.value:02X}) was found')
                    self._config_node(node_id)

                if restart:
                    self._nodes[node_id].reset()
                    self._config_node(node_id)

                self._status[node_id] = OpdNodeState.OFF
            else:
                if self._status[node_id] != OpdNodeState.NOT_FOUND:
                    logger.info(f'OPD node {node_id.name} (0x{node_id.value:02X}) was lost')
                    self._status[node_id] = OpdNodeState.NOT_FOUND
        except Max7310Error:
            logger.debug(f'OPD node {node_id.name} (0x{node_id.value:02X}) was not found')
            self._status[node_id] = OpdNodeState.NOT_FOUND

        return self._status[node_id] != OpdNodeState.NOT_FOUND

    def scan(self, restart: bool = False):
        '''
        Scan / probe for all nodes. This will turn on all battery cards found.

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

        for node_id in list(OpdNodeId):
            if self.probe(node_id, restart):
                count += 1

        # Turn on any battery cards found
        if self._status[OpdNodeId.BATTERY_0] == OpdNodeState.OFF:
            self.enable(OpdNodeId.BATTERY_0)
        if self._status[OpdNodeId.BATTERY_1] == OpdNodeState.OFF:
            self.enable(OpdNodeId.BATTERY_1)

        return count

    def enable(self, node_id: OpdNodeId):
        '''
        Enable an OPD node.

        Parameters
        ----------
        node_id: OpdNodeId
            The OPD node id to enable.
        '''

        logger.info(f'enabling OPD node {node_id.name} (0x{node_id.value:02X})')
        self._is_valid_and_sys_enabled(node_id)

        self._nodes[node_id].set_pin(self._ENABLE_PIN)
        self._status[node_id] = OpdNodeState.ON

    def disable(self, node_id: OpdNodeId):
        '''
        Disable an OPD node.

        Parameters
        ----------
        node_id: OpdNodeId
            The OPD node id to disable.
        '''

        logger.info(f'disabling OPD node {node_id.name} (0x{node_id.value:02X})')
        self._is_valid_and_sys_enabled(node_id)

        self._nodes[node_id].clear_pin(self._ENABLE_PIN)
        self._status[node_id] = OpdNodeState.OFF

    def reset(self, node_id: OpdNodeId):
        '''
        Reset a node on the OPD (disable and then re-enable it) Will try up to reset up
        to 3 times.

        Parameters
        ----------
        node_id: OpdNodeId
            The OPD node id to enable.
        '''

        self._is_valid_and_sys_enabled(node_id)

        reset = False

        for i in range(3):
            logger.info(f'reseting OPD node {node_id.name} (0x{node_id.value:02X}), try {i + 1}')
            try:
                self._nodes[node_id].set_pin(self._CB_RESET_PIN)
                sleep(self._NODE_RESET_DELAY_S)
                self._nodes[node_id].clear_pin(self._CB_RESET_PIN)

                if self._nodes[node_id].pin_status(self._NOT_FAULT_PIN):
                    self._status[node_id] = OpdNodeState.ON
                    reset = True
                    break
            except Max7310Error:
                continue

        if not reset:
            self._status[node_id] = OpdNodeState.DEAD
            logger.critical(f'OPD node {node_id.name} (0x{node_id.value:02X}) failed to reset 3 '
                            'times in a row, is now consider dead')

    def status(self, node_id: OpdNodeId) -> OpdNodeState:
        '''
        Get the Status of a node.

        Parameters
        ----------
        node_id: OpdNodeId
            The OPD node id to enable.

        Returns
        -------
        OpdNodeState
            The status of the OPD node.
        '''

        return self._status[node_id]

    def monitor_nodes(self):
        '''
        Check all nodes for faults. Will use batteries to check subsystem health as a whole
        as the batteries should always be on. If batteries are dead after 3 subsystem resets,
        this will mark the subsystem as dead.

        This should be called periodically in a loop.
        '''

        if self.is_subsystem_dead or not self.is_subsystem_enabled:
            return  # nothing to monitor

        good_states = [OpdNodeState.ON, OpdNodeState.OFF]

        for i in range(3):
            # batteries should always be on and are used to see if the subsystem is working
            bat0_was_alive = self._status[OpdNodeId.BATTERY_0] in good_states
            bat1_was_alive = self._status[OpdNodeId.BATTERY_1] in good_states

            for node_id in list(OpdNodeId):
                if self._status[node_id] == OpdNodeState.DEAD:
                    continue  # node is dead, can't do anything

                if not bool(self._nodes[node_id].input_port & 1 < self._NOT_FAULT_PIN):
                    logger.error(f'OPD node {node_id.name} (0x{node_id.value:02X}) circut '
                                 'breaker has tripped')
                    self._status[node_id] = OpdNodeState.ERROR
                    self.reset(node_id)

            # batteries should still be alive, after check for node faults
            reset = False
            if bat0_was_alive and self._status[OpdNodeId.BATTERY_0] == OpdNodeState.DEAD:
                reset = True
                logger.error(f'OPD node {OpdNodeId.BATTERY_0.name} '
                             f'(0x{OpdNodeId.BATTERY_0.value:02X}) died')
            if bat1_was_alive and self._status[OpdNodeId.BATTERY_1] == OpdNodeState.DEAD:
                reset = True
                logger.error(f'OPD node {OpdNodeId.BATTERY_1.name} '
                             f'(0x{OpdNodeId.BATTERY_1.value:02X}) died')

            # if batteries are dead, try to reset subsystem to fix
            if reset:
                logger.info(f'restarting OPD subsystem, try {i + 1}')
                self.restart()
            else:
                return  # all good

        if (bat0_was_alive and self._status[OpdNodeId.BATTERY_0] in OpdNodeState.DEAD) \
                or (bat1_was_alive and self._status[OpdNodeId.BATTERY_1] in OpdNodeState.DEAD):
            logger.critical('OPD monitor failed fix subsystem after 3 restarts, subsystem is '
                            'consider dead')
            self.disable()
            self._dead = True

    @property
    def is_subsystem_dead(self) -> bool:
        '''bool: OPD is dead or not.'''

        return self._dead
