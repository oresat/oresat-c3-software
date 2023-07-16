'''
State Service

This handles the main C3 state machine.
'''

from time import time

from olaf import Service, logger, NodeStop

from .. import C3State
from ..subsystems.fram import Fram, FramKey


class StateService(Service):

    BAT_LEVEL_HIGH = 7_000
    BAT_LEVEL_LOW = 6_500

    def __init__(self, fram: Fram):
        super().__init__()

        self._fram = fram
        self._attempts = 0

        self._boot_time = time()

    def on_start(self):

        self._attempts_obj = self.node.od['Deployment Control']['Attempts']
        persist_state_rec = self.node.od['Persistent State']
        self._deployed_obj = persist_state_rec['Deployed']
        self._last_edl_obj = persist_state_rec['Last EDL']
        self._c3_state_obj = self.node.od['C3 State']
        self._tx_timeout_obj = self.node.od['TX Control']['Timeout']
        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']
        self._last_tx_enable_obj = persist_state_rec['Last TX Enable']
        self._edl_timeout_obj = self.node.od['State Control']['EDL Timeout']
        self._pre_deploy_timeout_obj = self.node.od['Deployment Control']['Timeout']
        self._vbatt_bp1_obj = self.node.od['Battery 0']['VBatt BP1']
        self._vbatt_bp2_obj = self.node.od['Battery 0']['VBatt BP2']
        self._reset_timeout_obj = self.node.od['State Control']['Reset Timeout']

        self._fram_entry_co_objs = {
            FramKey.C3_STATE: self._c3_state_obj,
            FramKey.LAST_TIME_STAMP: persist_state_rec['Timestamp'],
            FramKey.ALARM_A: persist_state_rec['Alarm A'],
            FramKey.ALARM_B: persist_state_rec['Alarm B'],
            FramKey.WAKEUP: persist_state_rec['Wakeup'],
            FramKey.LAST_TX_ENABLE: self._last_tx_enable_obj,
            FramKey.LAST_EDL: self._last_edl_obj,
            FramKey.DEPLOYED: self._deployed_obj,
            FramKey.POWER_CYCLES: persist_state_rec['Power Cycles'],
            FramKey.LBAND_RX_BYTES: persist_state_rec['LBand RX Bytes'],
            FramKey.LBAND_RX_PACKETS: persist_state_rec['LBand RX Packets'],
            FramKey.VC1_SEQUENCE_COUNT: persist_state_rec['VC1 Sequence Count'],
            FramKey.VC1_EXPEDITE_COUNT: persist_state_rec['VC1 Expedite Count'],
            FramKey.EDL_SEQUENCE_COUNT: persist_state_rec['EDL Sequence Count'],
            FramKey.EDL_REJECTED_COUNT: persist_state_rec['EDL Rejected Count'],
            FramKey.CRYTO_KEY: self.node.od['Crypto Key'],
        }  # F-RAM entries for CANopen objects

        self._restore_state()

        self.node.add_sdo_write_callback(0x6005, self._on_cryto_key_write)
        self.node.add_sdo_read_callback(0x7000, self._on_c3_telemetery_read)

        # make sure the initial state is valid (will be invalid on a cleared F-RAM)
        if self._c3_state_obj.value not in list(C3State):
            self._c3_state_obj.value = C3State.PRE_DEPLOY.value

        self.loop = 0
        self.last_state = self._c3_state_obj.value
        logger.info(f'C3 initial state: {C3State(self.last_state).name}')

    def on_stop(self):

        self._store_state()

    def _on_cryto_key_write(self, index: int, subindex: int, data):
        '''On SDO write set the crypto key in OD and F-RAM'''

        if len(data) == 128:
            self._cryto_key_obj.value = data
            self._fram[FramKey.CRYTO_KEY] = data

    def _pre_deploy(self):

        if (self._boot_time + self._pre_deploy_timeout_obj.value) > time():
            if not self._tx_enabled_obj.value:
                self._tx_enabled_obj.value = True  # start beacons
                self._last_tx_enable_obj.value = time()
        else:
            logger.info('pre-deploy timeout reached')
            self._c3_state_obj.value = C3State.DEPLOY.value
            self._fram[FramKey.C3_STATE] = C3State.DEPLOY.value

    def _deploy(self):

        if not self._deployed_obj.value and self._attempts < self._attempts_obj.value:
            if self._bat_lvl_good:
                logger.info(f'deploying antennas, attempt {self._attempts}')
                # TODO deploy here
                self._attempts += 1
            # wait for battery to be at a good level
        else:
            logger.info('antennas deployed')
            self._c3_state_obj.value = C3State.STANDBY.value
            self._deployed_obj.value = True
            self._attempts = 0

    def _standby(self):

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif self._is_tx_enabled and self._bat_lvl_good:
            self._c3_state_obj.value = C3State.BEACON.value

    def _beacon(self):

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif not self._is_tx_enabled or not self._bat_lvl_good:
            self._c3_state_obj.value = C3State.STANDBY.value

    def _edl(self):

        if not self._is_edl_enabled:
            if self._is_tx_enabled and self._bat_lvl_good:
                self._c3_state_obj.value = C3State.BEACON.value
            else:
                self._c3_state_obj.value = C3State.STANDBY.value

    def on_loop(self):

        state_a = self._c3_state_obj.value
        if state_a != self.last_state:  # incase of change thru REST API
            logger.info(f'C3 state change: {C3State(self.last_state).name} -> '
                        f'{C3State(state_a).name}')

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            self._pre_deploy()
        elif self._c3_state_obj.value == C3State.DEPLOY:
            self._deploy()
        elif self._c3_state_obj.value == C3State.STANDBY:
            self._standby()
        elif self._c3_state_obj.value == C3State.BEACON:
            self._beacon()
        elif self._c3_state_obj.value == C3State.EDL:
            self._edl()
        else:
            logger.error(f'C3 invalid state: {self._c3_state_obj.value}, '
                         'resetting to PRE_DEPLOY')
            self._c3_state_obj.value = C3State.PRE_DEPLOY.value
            self.last_state = self._c3_state_obj.value
            return

        self.last_state = self._c3_state_obj.value
        if state_a != self.last_state:
            logger.info(f'C3 state change: {C3State(state_a).name} -> '
                        f'{C3State(self.last_state).name}')

        # only save state once a second
        loop = (self.loop + 1) % 10
        if loop == 0:
            self._store_state()

        self.sleep(0.1)

    @property
    def _is_tx_enabled(self) -> bool:
        '''bool: Helper property to check if the tx timeout has been reached.'''

        return (time() - self._last_tx_enable_obj.value) < self._tx_timeout_obj.value

    @property
    def _is_edl_enabled(self) -> bool:
        '''bool: Helper property to check if the edl timeout has been reached.'''

        return (time() - self._last_edl_obj.value) < self._edl_timeout_obj.value

    @property
    def _bat_lvl_good(self) -> bool:
        '''bool: Helper property to check if the battery levels are good.'''

        return self._vbatt_bp1_obj.value > self.BAT_LEVEL_LOW \
            and self._vbatt_bp2_obj.value > self.BAT_LEVEL_LOW

    @property
    def _trigger_reset(self) -> bool:
        '''bool: Helper property to check if the reset timeout has been reached.'''

        return (time() - self._boot_time) >= self._reset_timeout_obj.value

    def _store_state(self):

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY state

        for key in list(FramKey):
            if key == FramKey.CRYTO_KEY:
                continue  # static, skip this
            elif key == FramKey.LAST_TIME_STAMP:
                self._fram[key] = int(time())
            else:
                self._fram[key] = self._fram_entry_co_objs[key].value

    def _restore_state(self):

        values = self._fram.get_all()
        for key in list(FramKey):
            self._fram_entry_co_objs[key].value = values[key]

    def _on_c3_telemetery_read(self, index: int, subindex: int):

        if subindex == 1:
            return int(time() - self._boot_time)