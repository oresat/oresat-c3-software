'''
Everything todo with the OPD (OreSat Power Domain) functionality.

Every card, other than the solar cards, has a MAX7310 that can be used to turn the card or off.
'''

from enum import IntEnum
from time import sleep

from olaf import logger, Gpio, Adc

from ..drivers.max7310 import Max7310, Max7310Error


class OpdError(Exception):
    '''Error with :py:class:`Opd` or :py:class:`OpdNode`'''


class OpdNodeId(IntEnum):
    '''I2C addresses for all cards on the OPD'''

    BATTERY_1 = 0x18
    GPS = 0x19
    IMU = 0x1A
    DXWIFI = 0x1B
    STAR_TRACKER_1 = 0x1C
    CFC_PROCESSOR = 0x1D
    CFC_SENSOR = 0x1E
    BATTERY_2 = 0x1F
    RW_1 = 0x20
    RW_2 = 0x21
    RW_3 = 0x22
    RW_4 = 0x23

    @staticmethod
    def from_bytes(value: bytes):
        return OpdNodeId(int.from_bytes(value, 'little'))

    @property
    def is_stm32_card(self) -> bool:
        '''bool: Flag for if the OPD node is a STM32-based card.'''

        if self not in [OpdNodeId.GPS, OpdNodeId.DXWIFI, OpdNodeId.STAR_TRACKER_1,
                        OpdNodeId.CFC_PROCESSOR, OpdNodeId.CFC_SENSOR]:
            return True
        return False

    @property
    def is_octavo_card(self) -> bool:
        '''bool: Flag for if the OPD node is a Octavo A8-based card.'''

        if self in [OpdNodeId.GPS, OpdNodeId.DXWIFI, OpdNodeId.STAR_TRACKER_1,
                    OpdNodeId.CFC_PROCESSOR]:
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


class OpdNode:
    '''
    Base class for all OPD nodes

    NOTE: CFC sensor node does not have UART enable pin.
    '''

    _RESET_DELAY_S = 0.25

    _TIMEOUT_CONFIG = 1

    # these are consistent between all cards
    _NOT_FAULT_PIN = 2
    _ENABLE_PIN = 3
    _CB_RESET_PIN = 4

    def __init__(self, bus: int, node_id: OpdNodeId, mock: bool = False):
        '''
        Parameters
        ----------
        not_enable_pin: int
            Pin that enable the OPD subsystem.
        bus: int
            The I2C bus.
        mock: bool
            Mock the OPD subsystem.
        '''

        self._id = node_id
        self._mock = mock
        self._max7310 = Max7310(bus, node_id.value, mock)
        self._status = OpdNodeState.NOT_FOUND

    def __del__(self):

        try:
            self._max7310.output_clear(self._ENABLE_PIN)
        except Max7310Error:
            pass

    def configure(self):
        '''Configure the MAX7310 for the OPD node.'''

        inputs = 1 << self._NOT_FAULT_PIN
        self._max7310.configure(0, 0, inputs, self._TIMEOUT_CONFIG)
        if self._mock:
            self._max7310._mock_input_set(self._NOT_FAULT_PIN)
        self._status = OpdNodeState.OFF

    def probe(self, reset: bool = False) -> bool:
        '''
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
        '''

        logger.debug(f'probing OPD node {self.id.name} (0x{self.id.value:02X})')

        if self._status == OpdNodeState.DEAD:
            return False  # node is dead, no reason to probe

        try:
            if self._max7310.is_valid:
                if self._status == OpdNodeState.NOT_FOUND:
                    logger.info(f'OPD node {self.id.name} (0x{self.id.value:02X}) was found')
                    self.configure()

                if reset:
                    self._max7310.reset()
                    self.configure()

                self._status = OpdNodeState.OFF
            else:
                if self._status != OpdNodeState.NOT_FOUND:
                    logger.info(f'OPD node {self.id.name} (0x{self.id.value:02X}) was lost')
                    self._status = OpdNodeState.NOT_FOUND
        except Max7310Error as e:
            logger.error(f'MAX7310 error: {e}')
            logger.debug(f'OPD node {self.id.name} (0x{self.id.value:02X}) was not found')
            self._status = OpdNodeState.NOT_FOUND

        return self._status != OpdNodeState.NOT_FOUND

    def enable(self) -> OpdNodeState:
        '''
        Enable the OPD node.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        '''

        logger.info(f'enabling OPD node {self.id.name} (0x{self.id.value:02X})')

        if self._status == OpdNodeState.NOT_FOUND:
            return self._status  # cannot enable node that is NOT_FOUND

        try:
            self._max7310.output_set(self._ENABLE_PIN)
            self._status = OpdNodeState.ON
        except Max7310Error:
            self._status = OpdNodeState.ERROR

        return self._status

    def disable(self) -> OpdNodeState:
        '''
        Disable the OPD node.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        '''

        logger.info(f'disabling OPD node {self.id.name} (0x{self.id.value:02X})')

        if self._status == OpdNodeState.NOT_FOUND:
            return self._status  # cannot disable node that is NOT_FOUND

        try:
            self._max7310.output_clear(self._ENABLE_PIN)
            self._status = OpdNodeState.OFF
        except Max7310Error:
            self._status = OpdNodeState.ERROR

        return self._status

    def reset(self, attempts: int = 3) -> OpdNodeState:
        '''
        Reset a node on the OPD (disable and then re-enable it) Will try up to reset up
        to X times.

        Parameters
        ----------
        attempts: int
            The times to attempt to reset.
        '''

        reset = False

        for i in range(attempts):
            logger.debug(f'reseting OPD node {self.id.name} (0x{self.id.value:02X}), try {i + 1}')
            try:
                self._max7310.output_set(self._CB_RESET_PIN)
                sleep(self._RESET_DELAY_S)
                self._max7310.output_clear(self._CB_RESET_PIN)

                if self._mock:
                    self._max7310._mock_input_set(self._NOT_FAULT_PIN)

                if self.fault:
                    self._status = OpdNodeState.ERROR
                else:
                    self._status = OpdNodeState.ON
                    reset = True
                    break
            except Max7310Error:
                continue

        if not reset:
            self._status = OpdNodeState.DEAD
            logger.critical(f'OPD node {self.id.name} (0x{self.id.value:02X}) failed to reset 3 '
                            'times in a row, is now consider dead')

        return self._status

    def set_as_dead(self):
        '''Set the node as DEAD. only used by :py:class:`OpdResource`.'''

        self.disable()
        self._status = OpdNodeState.DEAD
        logger.info(f'OPD node {self.id.name} (0x{self.id.value:02X}) is set to DEAD')

    @property
    def id(self) -> OpdNodeId:
        '''OpdNodeId: Unique node ID.'''

        return self._id

    @property
    def status(self) -> OpdNodeState:
        '''OpdNodeState: Status of the OPD node.'''

        return self._status

    @property
    def is_enabled(self) -> bool:
        '''bool: The node is enabled.'''

        try:
            enabled = self._max7310.output_status(self._ENABLE_PIN)
        except Max7310Error as e:
            if self._status != OpdNodeState.NOT_FOUND:
                self._status = OpdNodeState.ERROR
            raise OpdError(e)

        return enabled

    @property
    def fault(self) -> bool:
        '''bool: The OPD fault pin has tripped.'''

        try:
            fault = not self._max7310.input_status(self._NOT_FAULT_PIN)
        except Max7310Error as e:
            if self._status != OpdNodeState.NOT_FOUND:
                self._status = OpdNodeState.ERROR
            raise OpdError(e)

        return fault


class OpdStm32Node(OpdNode):
    '''A STM32-based OPD Node'''

    _I2C_SCL_PIN = 0  # i2c bootloader
    _I2C_SDA_PIN = 1  # i2c bootloader
    _BOOT_PIN = 5  # bootloader
    _UART_PIN = 7  # connect to C3 UART

    def enable(self, bootloader_mode: bool = False) -> OpdNodeState:
        '''
        Enable the OPD node.

        Parameters
        ----------
        bootloader_mode: bool
            Boot into bootloader mode.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        '''

        try:
            if bootloader_mode:
                self._max7310.output_set(self._BOOT_PIN)
            else:
                self._max7310.output_clear(self._BOOT_PIN)
        except Max7310Error:
            self._status = OpdNodeState.ERROR
            return self._status

        return super().enable()

    def configure(self):
        '''Configure the MAX7310 for the OPD node.'''

        inputs = 1 << self._I2C_SCL_PIN | 1 << self._I2C_SDA_PIN | 1 << self._NOT_FAULT_PIN
        self._max7310.configure(0, 0, inputs, self._TIMEOUT_CONFIG)
        if self._mock:
            self._max7310._mock_input_set(self._NOT_FAULT_PIN)
        self._status = OpdNodeState.OFF

    def enable_uart(self):
        '''Connect the node the C3's UART'''

        self._max7310.output_set(self._UART_PIN)

    def disable_uart(self):
        '''Disconnect the node from the C3's UART'''

        self._max7310.output_clear(self._UART_PIN)

    @property
    def is_uart_enabled(self) -> bool:
        '''bool: Check if the UART pin is connected'''

        self._max7310.output_status(self._UART_PIN)


class OpdOctavoNode(OpdNode):
    '''A Octavo A8-based OPD Node'''

    _BOOT_PIN = 5  # boot select; eMMC or SD card
    _UART_PIN = 7  # connect to C3 UART

    def enable(self, boot_select: bool = True) -> OpdNodeState:
        '''
        Enable the OPD node.

        Parameters
        ----------
        boot_select: bool
            Boot of of eMMC or SD card. Not implemented yet.

        Returns
        -------
        OpdNodeState
            The node state after disabling the node.
        '''

        try:
            if boot_select:
                self._max7310.output_set(self._BOOT_PIN)
            else:
                self._max7310.output_clear(self._BOOT_PIN)
        except Max7310Error:
            self._status = OpdNodeState.ERROR
            return self._status

        return super().enable()

    def enable_uart(self):
        '''Connect the node the C3's UART'''

        self._max7310.output_set(self._UART_PIN)

    def disable_uart(self):
        '''Disconnect the node the C3's UART'''

        self._max7310.output_clear(self._UART_PIN)

    @property
    def is_uart_enabled(self) -> bool:
        '''bool: Check if the UART pin is connected'''

        self._max7310.output_status(self._UART_PIN)


class Opd:
    '''OreSat Power Domain.'''

    _SYS_RESET_DELAY_S = 10
    _RESET_ATTEMPTS = 3

    # values for getting opd current value from ADC pin
    _R_SET = 23_700  # ohms
    _MAX982L_CUR_RATIO = 965  # curret ratio

    def __init__(self, not_enable_pin: int, not_fault_pin: int, current_pin: int, bus: int,
                 mock: bool = False):
        '''
        Parameters
        ----------
        not_enable_pin: int
            Output pin that enables/disables the OPD subsystem.
        not_fault_pin: int
            Input pin for faults.
        current_pin: int
            ADC pin number to get OPD current.
        bus: int
            The I2C bus.
        mock: bool
            Mock the OPD subsystem.
        '''

        self._not_enable_pin = Gpio(not_enable_pin, mock)
        self._not_fault_pin = Gpio(not_fault_pin, mock)
        self._not_fault_pin._mock_value = 1  # fix default for mocking
        self._adc = Adc(current_pin, mock)
        self._not_enable_pin.high()  # make sure OPD disable initially

        self._nodes = {}
        for node_id in list(OpdNodeId):
            if node_id.is_stm32_card:
                node = OpdStm32Node(bus, node_id, mock)
            elif node_id.is_octavo_card:
                node = OpdOctavoNode(bus, node_id, mock)
            else:
                node = OpdNode(bus, node_id, mock)

            self._nodes[node_id] = node

        self._dead = False
        self.stop_loop = True

        self.enable()

    def __getitem__(self, node_id: OpdNodeId) -> OpdNode:

        return self._nodes[node_id]

    def __iter__(self) -> OpdNode:

        for p in list(OpdNodeId):
            yield self._nodes[p]

    def enable(self):
        '''Enable the OPD subsystem, will also do a scan.'''

        if self._dead:
            raise OpdError('OPD subsystem is consider dead')
        if self.is_subsystem_enabled:
            return  # already enabled

        logger.info('starting OPD subsystem')
        self._not_enable_pin.low()

        self.scan(True)

    def disable(self):
        '''Disable the OPD subsystem.'''

        logger.info('stopping OPD subsystem')

        for node in self:
            if node.status != OpdNodeState.NOT_FOUND:
                node.disable()

        self._not_enable_pin.high()

    def reset(self):
        '''Restart the OPD subsystem with a delay between stop and start.'''

        self.disable()
        sleep(self._SYS_RESET_DELAY_S)
        self.enable()

    def scan(self, reset: bool = False):
        '''
        Scan / probe for all nodes. This will turn on all battery cards found.

        Parameters
        ----------
        reset: bool
            Optional flag to reset any node that is found.

        Returns
        -------
        int
            The number of nodes found.
        '''

        count = 0

        for node in self._nodes.values():
            if node.probe(reset):
                count += 1

        # Turn on any battery cards found
        if self._nodes[OpdNodeId.BATTERY_1].status == OpdNodeState.OFF:
            self._nodes[OpdNodeId.BATTERY_1].enable()
        if self._nodes[OpdNodeId.BATTERY_2].status == OpdNodeState.OFF:
            self._nodes[OpdNodeId.BATTERY_2].enable()

        return count

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
        bat0_node = self._nodes[OpdNodeId.BATTERY_1]
        bat1_node = self._nodes[OpdNodeId.BATTERY_2]

        for i in range(self._RESET_ATTEMPTS):
            # batteries should always be on and are used to see if the subsystem is working
            bat0_was_alive = bat0_node.status in good_states
            bat1_was_alive = bat1_node.status in good_states

            # loop thru all node and reset any nodes with a fault
            for node in self._nodes.values():
                if self.stop_loop:
                    return  # these loop are time consuming, helps speed up service stop time

                if node.status not in [OpdNodeState.ON, OpdNodeState.ERROR]:
                    continue  # only can monitor nodes that are on

                try:
                    fault = node.fault
                except Max7310Error:
                    continue

                if fault:
                    logger.error(f'OPD node {node.id.name} (0x{node.id.value:02X}) circuit '
                                 f'breaker has tripped (in state {node.status.name})')
                    node.reset()

            # batteries should still be alive, after check for node faults
            reset = False
            if bat0_was_alive and bat0_node.status == OpdNodeState.DEAD:
                reset = True
                logger.error(f'OPD node {bat0_node.id.name} (0x{bat0_node.id.value:02X}) died')
            if bat1_was_alive and bat1_node.status == OpdNodeState.DEAD:
                reset = True
                logger.error(f'OPD node {bat1_node.id.name} (0x{bat1_node.id.value:02X}) died')

            # if batteries are dead, try to reset subsystem to fix
            if reset:
                logger.info(f'reseting OPD subsystem, try {i + 1}')
                self.reset()
            else:
                break  # opd subsystem is all good, no need to loop reset attempts

        if (bat0_was_alive and bat0_node.status == OpdNodeState.DEAD) \
                or (bat1_was_alive and bat1_node.status == OpdNodeState.DEAD):
            logger.critical(f'OPD monitor failed fix subsystem after {self._RESET_ATTEMPTS} '
                            'resets, subsystem is now consider dead')
            self.disable()
            self._dead = True

    @property
    def is_subsystem_dead(self) -> bool:
        '''bool: OPD is dead or not.'''

        return self._dead

    @property
    def is_subsystem_enabled(self) -> bool:
        '''bool: OPD is enabled or not.'''

        return not self._not_enable_pin.is_high

    @property
    def has_fault(self) -> bool:
        '''bool: OPD circuit has a fault.'''

        return not self._not_fault_pin.is_high

    @property
    def current(self) -> int:
        '''int: OPD current in milliamps.'''

        return int(self._adc.value * self._MAX982L_CUR_RATIO / self._R_SET * 1000)
