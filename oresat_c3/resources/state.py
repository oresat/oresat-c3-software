from threading import Thread, Event

from olaf import Resource, logger

from .. import C3State
from ..burnwire import deploy_helical, deploy_turnstile
from ..rtc import Rtc
from . import hard_reset


class StateResource(Resource):

    BAT_LEVEL_HIGH = 7_000
    BAT_LEVEL_LOW = 6_500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._rtc = Rtc(mock=True)
        self._boot_time = self._rtc.get_time()
        self._edl_eabled = False  # TODO replace with shared Edl class
        self._tx_enabledd = False

        self._event = Event()
        self._thread = Thread(target=self._send_beacon_thread)

    def on_start(self):

        self._restore_state()
        self._p_state_rec = self.od['Persistent State']
        self._c3_state_obj = self.od['C3 State']
        self._thread.start()

    def on_end(self):

        self._event.set()
        self._thread.join()

    def _send_beacon_thread(self):

        attempts = 0
        pre_deply_timeout = self.od['Deployment Control']['Timeout']
        while not self._event.is_set():
            if self._c3_state_obj.value == C3State.PRE_DEPLOY:
                if self._boot_time + pre_deply_timeout.value + self._rtc.get_time():
                    self._tx_enabled = True
                else:
                    logger.info('pre-deploy timeout reached')
                    self._c3_state_obj.value = C3State.DEPLOY.value
            elif self._c3_state_obj.value == C3State.DEPLOY:
                if not self._p_state_rec['Deployed'] and attempts < self._p_state_rec['Attempts'] \
                        and self._bat_good:
                    logger.info(f'deploying antennas, attempt {attempts}')
                    deploy_helical()
                    deploy_turnstile()
                    attempts += 1
                else:
                    self._c3_state_obj.value = C3State.STANDBY.value
                    self._p_state_rec['Deployed'] = True
                    logger.info('antennas deployed')
                    attempts = 0
            elif self._c3_state_obj.value == C3State.STANDBY:
                if self._edl_eabled:
                    self._c3_state_obj.value = C3State.EDL.value
                elif self._trigger_reset:
                    hard_reset()
                elif self._tx_enabled and self._bat_good:
                    self._c3_state_obj.value = C3State.BEACON.value
            elif self._c3_state_obj.value == C3State.BEACON:
                if self._edl_eabled:
                    self._c3_state_obj.value = C3State.EDL
                elif self._trigger_reset:
                    hard_reset()
                elif self._tx_enabled and not self._bat_good:
                    self._c3_state_obj.value = C3State.STANDBY.value
            elif self._c3_state_obj.value == C3State.EDL:
                if not self._edl_eabled:
                    if self._tx_enabled and self._bat_good:
                        self._c3_state_obj.value = C3State.BEACON.value
                    else:
                        self._c3_state_obj.value = C3State.STANDBY.value
            else:
                self._c3_state_obj.value = C3State.PRE_DEPLOY.value

            self._store_state()
            self._event.wait(0.1)

    @property
    def _bat_good(self) -> bool:
        '''bool: Helper property to check if the battery levels are good'''

        bat0_rec = self.od['Battery 0']
        return bat0_rec['VBatt BP1'] < self.BAT_LEVEL_LOW \
            and bat0_rec['VBatt BP2'] < self.BAT_LEVEL_LOW

    @property
    def _tigger_reset(self) -> bool:
        '''bool: Helper property to check if the reset timeout has been reached'''

        return self._rtc.get_time() - self._boot_time >= self._p_state_rec['Reset Timeout']

    def _store_state(self) -> bool:

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY

        # TODO persist_store(self.od, group)

    def _restore_state(self) -> bool:

        # TODO persist_restore(self.od, group)
        pass
