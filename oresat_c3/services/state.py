"""
C3 State Service

This handles the main C3 state machine.
"""

from time import time

from olaf import NodeStop, Service, logger

from .. import C3State
from ..subsystems.fram import Fram, FramKey


class StateService(Service):
    """C3 State Service."""

    BAT_LEVEL_LOW = 6_500  # in mV

    def __init__(self, fram: Fram):
        super().__init__()

        self._fram = fram
        self._attempts = 0
        self._loops = 0
        self._last_state = C3State.OFFLINE
        self._last_antennas_deploy = 0
        self._boot_time = time()
        self._fram_entry_co_objs = {}

    def on_start(self):
        edl_rec = self.node.od["edl"]
        antennas_rec = self.node.od["antennas"]
        tx_control_rec = self.node.od["tx_control"]
        bat_1_rec = self.node.od["battery_1"]

        self._c3_state_obj = self.node.od["status"]
        self._reset_timeout_obj = self.node.od["reset_timeout"]
        self._attempts_obj = antennas_rec["attempts"]
        self._deployed_obj = antennas_rec["deployed"]
        self._pre_deploy_timeout_obj = antennas_rec["pre_attempt_timeout"]
        self._ant_attempt_timeout_obj = antennas_rec["attempt_timeout"]
        self._ant_reattempt_timeout_obj = antennas_rec["reattempt_timeout"]
        self._tx_timeout_obj = tx_control_rec["timeout"]
        self._tx_enabled_obj = tx_control_rec["enable"]
        self._last_tx_enable_obj = tx_control_rec["last_enable_timestamp"]
        self._last_edl_obj = edl_rec["last_timestamp"]
        self._edl_timeout_obj = edl_rec["timeout"]
        self._vbatt_bp1_obj = bat_1_rec["pack_1_vbatt"]
        self._vbatt_bp2_obj = bat_1_rec["pack_2_vbatt"]

        self._fram_entry_co_objs = {
            FramKey.C3_STATE: self._c3_state_obj,
            FramKey.LAST_TIME_STAMP: None,
            FramKey.ALARM_A: None,
            FramKey.ALARM_B: None,
            FramKey.WAKEUP: None,
            FramKey.LAST_TX_ENABLE: self._last_tx_enable_obj,
            FramKey.LAST_EDL: self._last_edl_obj,
            FramKey.DEPLOYED: self._deployed_obj,
            FramKey.POWER_CYCLES: self.node.od["system"]["power_cycles"],
            FramKey.LBAND_RX_BYTES: self.node.od["lband"]["rx_bytes"],
            FramKey.LBAND_RX_PACKETS: self.node.od["lband"]["rx_packets"],
            FramKey.VC1_SEQUENCE_COUNT: edl_rec["vc1_sequence_count"],
            FramKey.VC1_EXPEDITE_COUNT: edl_rec["vc1_expedite_count"],
            FramKey.EDL_SEQUENCE_COUNT: edl_rec["sequence_count"],
            FramKey.EDL_REJECTED_COUNT: edl_rec["rejected_count"],
            FramKey.CRYTO_KEY_0: edl_rec["key0"],
            FramKey.CRYTO_KEY_1: edl_rec["key1"],
            FramKey.CRYTO_KEY_2: edl_rec["key2"],
            FramKey.CRYTO_KEY_3: edl_rec["key3"],
            FramKey.CRYTO_ACTIVE_KEY: edl_rec["active_key"],
        }  # F-RAM entries for CANopen objects

        self._restore_state()

        # TODO
        # self.node.add_sdo_write_callback(0x6005, self._on_cryto_key_write)

        # make sure the initial state is valid (will be invalid on a cleared F-RAM)
        if self._c3_state_obj.value not in list(C3State):
            self._c3_state_obj.value = C3State.PRE_DEPLOY.value

        self._last_state = self._c3_state_obj.value
        logger.info(f"C3 initial state: {C3State(self._last_state).name}")

    def on_stop(self):
        self._store_state()

    def _on_cryto_key_write(self, data: bytes):
        """On SDO write set the crypto key in OD and F-RAM"""

        if len(data) == 32:
            # self._cryto_key_obj.value = data
            self._fram[FramKey.CRYTO_KEY_0] = data

    def _pre_deploy(self):
        """PRE_DEPLOY state method."""

        if (self._boot_time + self._pre_deploy_timeout_obj.value) > time():
            if not self._tx_enabled_obj.value:
                self._tx_enabled_obj.value = True  # start beacons
                self._last_tx_enable_obj.value = int(time())
        else:
            logger.info("pre-deploy timeout reached")
            self._c3_state_obj.value = C3State.DEPLOY.value
            self._fram[FramKey.C3_STATE] = C3State.DEPLOY.value

    def _deploy(self):
        """DEPLOY state method."""

        if not self._deployed_obj.value and self._attempts < self._attempts_obj.value:
            if (
                time() > self._last_antennas_deploy + self._ant_reattempt_timeout_obj.value
                and self._bat_lvl_good
            ):
                logger.info(f"deploying antennas, attempt {self._attempts + 1}")
                # TODO deploy
                self._last_antennas_deploy = time()
                self._attempts += 1
            # wait for battery to be at a good level
        else:
            logger.info("antennas deployed")
            self._c3_state_obj.value = C3State.STANDBY.value
            self._deployed_obj.value = True
            self._attempts = 0

    def _standby(self):
        """STANDBY state method."""

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif self._is_tx_enabled and self._bat_lvl_good:
            self._c3_state_obj.value = C3State.BEACON.value

    def _beacon(self):
        """BEACON state method."""

        if self._is_edl_enabled:
            self._c3_state_obj.value = C3State.EDL.value
        elif self._trigger_reset:
            self.node.stop(NodeStop.HARD_RESET)
        elif not self._is_tx_enabled or not self._bat_lvl_good:
            self._c3_state_obj.value = C3State.STANDBY.value

    def _edl(self):
        """EDL state method."""

        if not self._is_edl_enabled:
            if self._is_tx_enabled and self._bat_lvl_good:
                self._c3_state_obj.value = C3State.BEACON.value
            else:
                self._c3_state_obj.value = C3State.STANDBY.value

    def on_loop(self):
        state_a = self._c3_state_obj.value
        if state_a != self._last_state:  # incase of change thru REST API
            logger.info(
                f"C3 state change: {C3State(self._last_state).name} -> {C3State(state_a).name}"
            )

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
            logger.error(f"C3 invalid state: {self._c3_state_obj.value}, resetting to PRE_DEPLOY")
            self._c3_state_obj.value = C3State.PRE_DEPLOY.value
            self._last_state = self._c3_state_obj.value
            return

        self._last_state = self._c3_state_obj.value
        if state_a != self._last_state:
            logger.info(
                f"C3 state change: {C3State(state_a).name} -> {C3State(self._last_state).name}"
            )

        # only save state once a second
        self._loops += 1
        self._loops %= 10
        if self._loops == 0:
            self._store_state()

        self.sleep(0.1)

    @property
    def _is_tx_enabled(self) -> bool:
        """bool: Helper property to check if the tx timeout has been reached."""

        return (time() - self._last_tx_enable_obj.value) < self._tx_timeout_obj.value

    @property
    def _is_edl_enabled(self) -> bool:
        """bool: Helper property to check if the edl timeout has been reached."""

        return (time() - self._last_edl_obj.value) < self._edl_timeout_obj.value

    @property
    def _bat_lvl_good(self) -> bool:
        """bool: Helper property to check if the battery levels are good."""

        return (
            self._vbatt_bp1_obj.value > self.BAT_LEVEL_LOW
            and self._vbatt_bp2_obj.value > self.BAT_LEVEL_LOW
        )

    @property
    def _trigger_reset(self) -> bool:
        """bool: Helper property to check if the reset timeout has been reached."""

        return (time() - self._boot_time) >= self._reset_timeout_obj.value

    def _store_state(self):
        """store the state in F-RAM."""

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY state

        for key in list(FramKey):
            if self._fram_entry_co_objs[key] is None or key in [
                FramKey.CRYTO_KEY_0,
                FramKey.CRYTO_KEY_1,
                FramKey.CRYTO_KEY_2,
                FramKey.CRYTO_KEY_3,
            ]:
                continue  # deprecated or static, skip these

            self._fram[key] = self._fram_entry_co_objs[key].value

    def _restore_state(self):
        """restore the state from F-RAM."""

        values = self._fram.get_all()
        for key in list(FramKey):
            if self._fram_entry_co_objs[key] is None:
                continue  # deprecated, skip these
            self._fram_entry_co_objs[key].value = values[key]
