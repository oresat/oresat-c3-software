'''
State Resource

This handles the main C3 state machine.
'''

from threading import Thread, Event

from olaf import Resource, logger

from .. import C3State
from ..subsystems.rtc import Rtc
from . import hard_reset


class StateResource(Resource):

    BAT_LEVEL_HIGH = 7_000
    BAT_LEVEL_LOW = 6_500

    def __init__(self, rtc: Rtc):
        super().__init__()

        self.rtc = rtc
        self._attempts = 0

        self._boot_time = self.rtc.get_time()

        self._event = Event()
        self._thread = Thread(target=self._send_beacon_thread)

    def on_start(self):

        self._restore_state()

        self._attempts_obj = self.node.od['Deployment Control']['Attempts']
        self._deploy_obj = self.node.od['Persistent State']['Deployed']
        self._c3_state_obj = self.node.od['C3 State']
        self._tx_enabled_obj = self.node.od['TX Control']['Enabled']
        self._pre_deply_timeout_obj = self.node.od['Deployment Control']['Timeout']
        self._vbatt_bp1_obj = self.node.od['Battery 0']['VBatt BP1']
        self._vbatt_bp1_obj = self.node.od['Battery 0']['VBatt BP2']

        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _pre_deploy(self):

        if self._boot_time + self._pre_deply_timeout_obj.value + self.rtc.get_time():
            self._tx_enabled_obj.value = True
        else:
            logger.info('pre-deploy timeout reached')
            self._c3_state_obj.value = C3State.DEPLOY.value

    def _deploy(self):

        if not self._deploy_obj.value and self._attempts < self._attempts_obj.value \
                and self._bat_good:
            logger.info(f'deploying antennas, attempt {self._attempts}')
            # TODO deploy here
            self._attempts += 1
        else:
            self._c3_state_obj.value = C3State.STANDBY.value
            self._deploy_obj.value = True
            logger.info('antennas deployed')
            self._attempts = 0

    def _standby(self):

        if self._edl.is_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            hard_reset()
        elif self._tx_enabled_obj.value and self._bat_good:
            self._c3_state_obj.value = C3State.BEACON.value

    def _beacon(self):

        if self._edl.is_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            hard_reset()
        elif self._tx_enabled_obj.value and not self._bat_good:
            self._c3_state_obj.value = C3State.STANDBY.value

    def edl(self):

        if not self._edl.is_enabled:
            if self._tx_enabled_obj.value and self._bat_good:
                self._c3_state_obj.value = C3State.BEACON.value
            else:
                self._c3_state_obj.value = C3State.STANDBY.value

    def _send_beacon_thread(self):

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

            self._store_state()
            self._event.wait(0.1)

    @property
    def _bat_good(self) -> bool:
        '''bool: Helper property to check if the battery levels are good'''

        return self._vbatt_bp1_obj < self.BAT_LEVEL_LOW or self._vbatt_bp2_obj < self.BAT_LEVEL_LOW

    @property
    def _tigger_reset(self) -> bool:
        '''bool: Helper property to check if the reset timeout has been reached'''

        return self.rtc.get_time() - self._boot_time >= self._p_state_rec['Reset Timeout']

    def _store_state(self) -> bool:

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY

        # TODO persist_store(self.node.od, group)

    def _restore_state(self) -> bool:

        # TODO persist_restore(self.node.od, group)
        pass
