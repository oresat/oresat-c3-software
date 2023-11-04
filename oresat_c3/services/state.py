"""
C3 State Service

This handles the main C3 state machine.
"""

from time import time

import canopen
from olaf import NodeStop, Service, logger

from .. import C3State
from ..drivers.fm24cl64b import Fm24cl64b
from ..subsystems.antennas import Antennas


class StateService(Service):
    """C3 State Service."""

    BAT_LEVEL_LOW = 6500  # in mV

    def __init__(self, fram: Fm24cl64b, fram_objs: list, antennas: Antennas):
        super().__init__()

        self._fram = fram
        self._fram_objs = fram_objs
        self._antennas = antennas
        self._attempts = 0
        self._loops = 0
        self._last_state = C3State.OFFLINE
        self._last_antennas_deploy = 0
        self._boot_time = time()

        self._c3_state_obj: canopen.objectdictionary.Variable = None
        self._reset_timeout_obj: canopen.objectdictionary.Variable = None
        self._attempts_obj: canopen.objectdictionary.Variable = None
        self._deployed_obj: canopen.objectdictionary.Variable = None
        self._pre_deploy_timeout_obj: canopen.objectdictionary.Variable = None
        self._ant_attempt_timeout_obj: canopen.objectdictionary.Variable = None
        self._ant_attempt_between_timeout_obj: canopen.objectdictionary.Variable = None
        self._ant_reattempt_timeout_obj: canopen.objectdictionary.Variable = None
        self._tx_timeout_obj: canopen.objectdictionary.Variable = None
        self._tx_enable_obj: canopen.objectdictionary.Variable = None
        self._last_tx_enable_obj: canopen.objectdictionary.Variable = None
        self._last_edl_obj: canopen.objectdictionary.Variable = None
        self._edl_timeout_obj: canopen.objectdictionary.Variable = None
        self._vbatt_bp1_obj: canopen.objectdictionary.Variable = None
        self._vbatt_bp2_obj: canopen.objectdictionary.Variable = None

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
        self._ant_attempt_between_timeout_obj = antennas_rec["attempt_between_timeout"]
        self._ant_reattempt_timeout_obj = antennas_rec["reattempt_timeout"]
        self._tx_timeout_obj = tx_control_rec["timeout"]
        self._tx_enable_obj = tx_control_rec["enable"]
        self._last_tx_enable_obj = tx_control_rec["last_enable_timestamp"]
        self._last_edl_obj = edl_rec["last_timestamp"]
        self._edl_timeout_obj = edl_rec["timeout"]
        self._vbatt_bp1_obj = bat_1_rec["pack_1_vbatt"]
        self._vbatt_bp2_obj = bat_1_rec["pack_2_vbatt"]

        self._restore_state()

        self.node.add_sdo_callbacks("tx_control", "enable", None, self._on_write_tx_enable)

        # make sure the initial state is valid (will be invalid on a cleared F-RAM)
        if self._c3_state_obj.value not in list(C3State):
            self._c3_state_obj.value = C3State.PRE_DEPLOY.value

        self._last_state = self._c3_state_obj.value
        logger.info(f"C3 initial state: {C3State(self._last_state).name}")

    def on_stop(self):
        self._store_state()

    def _on_write_tx_enable(self, data: bool):
        """On SDO write set tx enable and last enable timestamp objects."""

        self._tx_enable_obj.value = data
        if data:
            logger.info("enabling tx")
            self._last_tx_enable_obj.value = int(time())
        else:
            logger.info("disabling tx")
            self._last_tx_enable_obj.value = 0

    def _pre_deploy(self):
        """PRE_DEPLOY state method."""

        if (self._boot_time + self._pre_deploy_timeout_obj.value) > time():
            if not self._tx_enable_obj.value:
                self._tx_enable_obj.value = True  # start beacons
                self._last_tx_enable_obj.value = int(time())
        else:
            logger.info("pre-deploy timeout reached")
            self._c3_state_obj.value = C3State.DEPLOY.value

    def _deploy(self):
        """DEPLOY state method."""

        if not self._deployed_obj.value and self._attempts < self._attempts_obj.value:
            if (
                time() > self._last_antennas_deploy + self._ant_reattempt_timeout_obj.value
                and self.is_bat_lvl_good
            ):
                logger.info(f"deploying antennas, attempt {self._attempts + 1}")
                self._antennas.deploy(
                    self._ant_attempt_timeout_obj.value,
                    self._ant_attempt_between_timeout_obj.value,
                )
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

        if self.has_edl_timed_out:
            self._c3_state_obj.value = C3State.EDL.value
        elif self.has_reset_timed_out:
            self.node.stop(NodeStop.HARD_RESET)
        elif self.has_tx_timed_out and self.is_bat_lvl_good:
            self._c3_state_obj.value = C3State.BEACON.value

    def _beacon(self):
        """BEACON state method."""

        if self.has_edl_timed_out:
            self._c3_state_obj.value = C3State.EDL.value
        elif self.has_reset_timed_out:
            self.node.stop(NodeStop.HARD_RESET)
        elif not self.has_tx_timed_out or not self.is_bat_lvl_good:
            self._c3_state_obj.value = C3State.STANDBY.value

    def _edl(self):
        """EDL state method."""

        if not self.has_edl_timed_out:
            if self.has_tx_timed_out and self.is_bat_lvl_good:
                self._c3_state_obj.value = C3State.BEACON.value
            else:
                self._c3_state_obj.value = C3State.STANDBY.value

    def on_loop(self):
        state_a = self._c3_state_obj.value
        if state_a != self._last_state:  # incase of change thru REST API
            logger.info(f"tx en: {self._tx_enable_obj.value} | bat good: {self.is_bat_lvl_good}")
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
            logger.info(f"tx en: {self._tx_enable_obj.value} | bat good: {self.is_bat_lvl_good}")
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
    def has_tx_timed_out(self) -> bool:
        """bool: Helper property to check if the tx timeout has been reached."""

        return (time() - self._last_tx_enable_obj.value) < self._tx_timeout_obj.value

    @property
    def has_edl_timed_out(self) -> bool:
        """bool: Helper property to check if the edl timeout has been reached."""

        return (time() - self._last_edl_obj.value) < self._edl_timeout_obj.value

    @property
    def is_bat_lvl_good(self) -> bool:
        """bool: Helper property to check if the battery levels are good."""

        return (
            self._vbatt_bp1_obj.value > self.BAT_LEVEL_LOW
            and self._vbatt_bp2_obj.value > self.BAT_LEVEL_LOW
        )

    @property
    def has_reset_timed_out(self) -> bool:
        """bool: Helper property to check if the reset timeout has been reached."""

        return (time() - self._boot_time) >= self._reset_timeout_obj.value

    def _store_state(self):
        """Store the state in F-RAM."""

        if self._c3_state_obj.value == C3State.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY state

        offset = 0
        for obj in self._fram_objs:
            if obj.data_type == canopen.objectdictionary.DOMAIN:
                continue

            if obj.data_type == canopen.objectdictionary.OCTET_STRING:
                raw = obj.value
                raw_len = len(obj.default)
            else:
                raw = obj.encode_raw(obj.value)
                raw_len = len(raw)

            self._fram.write(offset, raw)
            offset += raw_len

    def _restore_state(self):
        """Restore the state from F-RAM."""

        offset = 0
        for obj in self._fram_objs:
            if obj.data_type == canopen.objectdictionary.DOMAIN:
                continue

            if obj.data_type == canopen.objectdictionary.OCTET_STRING:
                size = len(obj.default)
                obj.value = self._fram.read(offset, size)
            else:
                size = len(obj.encode_raw(obj.default))
                raw = self._fram.read(offset, size)
                obj.value = obj.decode_raw(raw)
            offset += size
