'''
State Resource

This handles the main C3 state machine.
'''

from time import time
from threading import Thread, Event

from olaf import Resource, logger, NodeStop

from .. import C3State
from ..subsystems.fram import Fram, FramKey


class StateResource(Resource):

    BAT_LEVEL_HIGH = 7_000
    BAT_LEVEL_LOW = 6_500

    def __init__(self, fram: Fram):
        super().__init__()

        self._fram = fram
        self._attempts = 0

        self._boot_time = time()

        self._event = Event()
        self._thread = Thread(target=self._state_machine_thread)

    def on_start(self):

        self._attempts_obj = self.node.od['Deployment Control']['Attempts']
        persist_state_rec = self.node.od['Persistent State']
        self._deployed_obj = persist_state_rec['Deployed']
        self._last_edl = persist_state_rec['Last EDL']
        self._c3_state_obj = self.node.od['C3 State']
        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']
        self._edl_timeout_obj = self.node.od['State Control']['EDL Timeout']
        self._pre_deply_timeout_obj = self.node.od['Deployment Control']['Timeout']
        self._vbatt_bp1_obj = self.node.od['Battery 0']['VBatt BP1']
        self._vbatt_bp1_obj = self.node.od['Battery 0']['VBatt BP2']

        self._fram_entry_co_objs = {
            FramKey.C3_STATE: self._c3_state_obj,
            FramKey.LAST_TIME_STAMP: persist_state_rec['Timestamp'],
            FramKey.ALARM_A: persist_state_rec['Alarm A'],
            FramKey.ALARM_B: persist_state_rec['Alarm B'],
            FramKey.WAKEUP: persist_state_rec['Wakeup'],
            FramKey.LAST_TX_ENABLE: persist_state_rec['Last TX Enable'],
            FramKey.LAST_EDL: self._last_edl,
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

        self._thread.start()

    def on_end(self):

        self._store_state()

        self._event.set()
        self._thread.join()

    def _on_cryto_key_write(self, index: int, subindex: int, data):
        '''On SDO write set the crypto key in OD and F-RAM'''

        if len(data) == 128:
            self._cryto_key_obj.value = data
            self._fram[FramKey.CRYTO_KEY] = data

    def _pre_deploy(self):

        if self._boot_time + self._pre_deply_timeout_obj.value < time():
            self._tx_enabled_obj.value = True  # start beacons
        else:
            logger.info('pre-deploy timeout reached')
            self._c3_state_obj.value = C3State.DEPLOY.value
            self._fram[FramKey.C3_STATE] = C3State.DEPLOYED.value

    def _deploy(self):

        if not self._deployed_obj.value and self._attempts < self._attempts_obj.value \
                and self._bat_good:
            logger.info(f'deploying antennas, attempt {self._attempts}')
            # TODO deploy here
            self._attempts += 1
        else:
            self._c3_state_obj.value = C3State.STANDBY.value
            self._fram[FramKey.C3_STATE] = C3State.STANDBY.value
            self._deployed_obj.value = True
            self._fram[FramKey.DEPLOYED] = True
            logger.info('antennas deployed')
            self._attempts = 0

    def _standby(self):

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif self._tx_enabled_obj.value and self._bat_good:
            self._c3_state_obj.value = C3State.BEACON.value

    def _beacon(self):

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif self._tx_enabled_obj.value and not self._bat_good:
            self._c3_state_obj.value = C3State.STANDBY.value

    def _edl(self):

        if not self._is_edl_enabled:
            if self._tx_enabled_obj.value and self._bat_good:
                self._c3_state_obj.value = C3State.BEACON.value
            else:
                self._c3_state_obj.value = C3State.STANDBY.value

    def _state_machine_thread(self):

        loop = 0
        while not self._event.is_set():
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
                self._c3_state_obj.value = C3State.PRE_DEPLOY.value

            # only save state once a second
            loop = (loop + 1) % 10
            if loop == 0:
                self._store_state()

            self._event.wait(0.1)

    @property
    def _is_edl_enabled(self) -> bool:
        '''bool: Helper property to check if the edl timeout has been reached.'''

        return time() - self._last_edl.value < self._edl_timeout_obj.value

    @property
    def _bat_good(self) -> bool:
        '''bool: Helper property to check if the battery levels are good'''

        return self._vbatt_bp1_obj < self.BAT_LEVEL_LOW or self._vbatt_bp2_obj < self.BAT_LEVEL_LOW

    @property
    def _tigger_reset(self) -> bool:
        '''bool: Helper property to check if the reset timeout has been reached'''

        return time() - self._boot_time >= self._p_state_rec['Reset Timeout']

    def _store_state(self):

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY state

        for key in list(FramKey):
            if key == FramKey.CRYTO_KEY:
                continue  # static, skip this
            self._fram[key] = self._fram_entry_co_objs[key].value

    def _restore_state(self):

        values = self._fram.get_all()
        for key in list(FramKey):
            self._fram_entry_co_objs[key].value = values[key]
