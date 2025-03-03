import os
import subprocess
from time import monotonic, time

from loguru import logger
from oresat_libcanopend import DataType, NodeClient

from ..drivers.fm24cl64b import Fm24cl64b
from ..gen.fram import FRAM_DEF
from ..gen.od import C3Entry, Status, SystemReset, UpdaterStatus
from ..subsystems.antennas import Antennas
from ..subsystems.rtc import set_rtc_time
from . import Service


class StateService(Service):
    BAT_LEVEL_LOW = 6500  # in mV
    I2C_BUS_NUM = 2
    FRAM_I2C_ADDR = 0x50

    def __init__(self, node: NodeClient, mock_hw: bool = False):
        super().__init__(node)

        self._fram = Fm24cl64b(self.I2C_BUS_NUM, self.FRAM_I2C_ADDR, mock_hw)
        self._antennas = Antennas(mock_hw)
        self._attempts = 0
        self._loops = 0
        self._last_state = Status.PRE_DEPLOY
        self._last_antennas_deploy = 0
        self._start_time = monotonic()

        self.restore_state()
        if not self.node.od_read(C3Entry.TX_CONTROL_ENABLE):
            self.node.od_write(C3Entry.EDL_LAST_TIMESTAMP, 0)
        if self.node.od_read(C3Entry.STATUS) == Status.EDL:
            self.node.od_write(C3Entry.STATUS, Status.STANDBY)

        self.node.add_write_callback(C3Entry.TX_CONTROL_ENABLE, self._on_write_tx_enable)

        self._last_state = self.node.od_read(C3Entry.STATUS)
        logger.info(f"C3 initial state: {self._last_state.name}")

        self._start_time = monotonic()

    def on_stop(self):
        self.store_state()

    def _on_write_tx_enable(self, data: bool):
        """On SDO write set tx enable and last enable timestamp objects."""

        self.node.od_write(C3Entry.TX_CONTROL_ENABLE, data)
        if data:
            logger.info("enabling tx")
            self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, int(time()))
        else:
            logger.info("disabling tx")
            self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, 0)

    def _reset(self):
        if self.node.od_write(C3Entry.UPDATER_STATUS) == UpdaterStatus.IN_PROGRESS:
            return

        logger.info("system reset")

        result = subprocess.run(
            ["systemctl", "stop", "oresat-c3-watchdog"],
            shell=True,
            check=False,
            capture_output=True,
        )

        if result.returncode != 0:
            logger.error("stopping watchdog app failed, doing a hard reset")
            self.node.od_write(C3Entry.SYSTEM_RESET, SystemReset.HARD_RESET)

    def _pre_deploy(self):
        """PRE_DEPLOY state method."""

        pre_attempt_timeout = self.node.od_read(C3Entry.ANTENNAS_PRE_ATTEMPT_TIMEOUT)
        if (monotonic() - self._start_time) < pre_attempt_timeout:
            if not self.node.od_read(C3Entry.TX_CONTROL_ENABLE):
                self.node.od_write(C3Entry.TX_CONTROL_ENABLE, True)  # start beacons
                self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, int(time()))
        else:
            logger.info("pre-deploy timeout reached")
            self.node.od_write(C3Entry.STATUS, Status.DEPLOY)

    def _deploy(self):
        """DEPLOY state method."""

        reattempt_timeout = self.node.od_read(C3Entry.ANTENNAS_REATTEMPT_TIMEOUT)
        antennas_deployed = self.node.od_read(C3Entry.ANTENNAS_DEPLOYED)
        antennas_attempts = self.node.od_read(C3Entry.ANTENNAS_ATTEMPTS)

        if not antennas_deployed and self._attempts < antennas_attempts:
            if (
                monotonic() > (self._last_antennas_deploy + reattempt_timeout)
            ) and self.is_bat_lvl_good:
                logger.info(f"deploying antennas, attempt {self._attempts + 1}")
                self._antennas.deploy(
                    self.node.od_read(C3Entry.ANTENNAS_ATTEMPTS_TIMEOUT),
                    self.node.od_read(C3Entry.ANTENNAS_ATTEMPT_BETWEEN_TIMEOUT),
                )
                self._last_antennas_deploy = monotonic()
                self._attempts += 1
            # wait for battery to be at a good level
        else:
            logger.info("antennas deployed")
            self.node.od_write(C3Entry.STATUS, Status.STANDBY)
            self.node.od_write(C3Entry.ANTENNAS_DEPLOYED, True)
            self._attempts = 0

    def _standby(self):
        """STANDBY state method."""

        if self.has_edl_timed_out:
            self.node.od_write(C3Entry.STATUS, Status.EDL)
        elif self.has_reset_timed_out:
            self._reset()
        elif not self.has_tx_timed_out and self.is_bat_lvl_good:
            self.node.od_write(C3Entry.STATUS, Status.BEACON)

    def _beacon(self):
        """BEACON state method."""

        if self.has_edl_timed_out:
            self.node.od_write(C3Entry.STATUS, Status.EDL)
        elif self.has_reset_timed_out:
            self._reset()
        elif self.has_tx_timed_out or not self.is_bat_lvl_good:
            self.node.od_write(C3Entry.STATUS, Status.STANDBY)

    def _edl(self):
        """EDL state method."""

        if not self.has_edl_timed_out:
            if not self.has_tx_timed_out and self.is_bat_lvl_good:
                self.node.od_write(C3Entry.STATUS, Status.BEACON)
            else:
                self.node.od_write(C3Entry.STATUS, Status.STANDBY)

    def on_loop(self):
        if self.has_tx_timed_out and self.node.od_read(C3Entry.TX_CONTROL_ENABLE):
            logger.info("tx enable timeout")
            self.node.od_write(C3Entry.TX_CONTROL_ENABLE, False)

        state = self.node.od_read(C3Entry.STATUS)
        if state != self._last_state:  # incase of change thru REST API
            logger.info(
                f"tx en: {self.node.od_read(C3Entry.TX_CONTROL_ENABLE)} "
                f"| bat good: {self.is_bat_lvl_good}"
            )
            logger.info(f"C3 state change: {self._last_state.name} -> {state.name}")

        if state == Status.PRE_DEPLOY:
            self._pre_deploy()
        elif state == Status.DEPLOY:
            self._deploy()
        elif state == Status.STANDBY:
            self._standby()
        elif state == Status.BEACON:
            self._beacon()
        elif state == Status.EDL:
            self._edl()
        else:
            logger.error(f"C3 invalid state: {self._c3_state_obj.value}, resetting to PRE_DEPLOY")
            self._c3_state_obj.value = Status.PRE_DEPLOY.value
            self._last_state = self._c3_state_obj.value
            return

        self._last_state = self.node.od_read(C3Entry.STATUS)
        if state != self._last_state:
            logger.info(
                f"tx en: {self.node.od_read(C3Entry.TX_CONTROL_ENABLE)} "
                f"| bat good: {self.is_bat_lvl_good}"
            )
            logger.info(f"C3 state change: {state.name} -> {self._last_state.name}")

        # only save state once a second
        self._loops += 1
        self._loops %= 10
        if self._loops == 0:
            self.store_state()

        self.sleep(0.1)

    @property
    def has_tx_timed_out(self) -> bool:
        """bool: Helper property to check if the tx timeout has been reached."""

        return (
            time() - self.node.od_read(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP)
        ) > self.node.od_read(C3Entry.TX_CONTROL_TIMEOUT)

    @property
    def has_edl_timed_out(self) -> bool:
        """bool: Helper property to check if the edl timeout has been reached."""

        return (time() - self.node.od_read(C3Entry.EDL_LAST_TIMESTAMP)) < self.node.od_read(
            C3Entry.EDL_TIMEOUT
        )

    @property
    def is_bat_lvl_good(self) -> bool:
        """bool: Helper property to check if the battery levels are good."""

        vbatt_bp1 = self.node.od_read(C3Entry.BATTERY_1_PACK_1_VBATT)
        vbatt_bp2 = self.node.od_read(C3Entry.BATTERY_1_PACK_2_VBATT)
        return vbatt_bp1 > self.BAT_LEVEL_LOW and vbatt_bp2 > self.BAT_LEVEL_LOW

    @property
    def has_reset_timed_out(self) -> bool:
        """bool: Helper property to check if the reset timeout has been reached."""

        if os.geteuid() != 0 or not self.node.od_read(C3Entry.FLIGHT_MODE):
            return False

        return (monotonic() - self._start_time) > self.node.od_read(C3Entry.RESET_TIMEOUT)

    def store_state(self):
        """Store the state in F-RAM."""

        if self.node.od_read(C3Entry.STATUS) == Status.PRE_DEPLOY:
            return  # Do not store state in PRE_DEPLOY state

        offset = 0
        for entry in FRAM_DEF:
            if entry.data_type == DataType.BYTES:
                raw = self.node.od_read(entry, use_enum=False)
                raw_len = len(entry.default)
            else:
                value = self.node.od_read(entry, use_enum=False)
                raw = entry.encode(value)
                raw_len = len(raw)

            self._fram.write(offset, raw)
            offset += raw_len

    def restore_state(self):
        """Restore the state from F-RAM."""

        offset = 0
        for entry in FRAM_DEF:
            if entry.data_type == DataType.BYTES:
                size = len(entry.default)
                raw = self._fram.read(offset, size)
                self.node.od_write(entry, raw)
            else:
                size = len(entry.encode(entry.default))
                raw = self._fram.read(offset, size)
                value = entry.decode(raw)
                if entry == C3Entry.STATUS and value not in Status:  # incase of empty FRAM
                    value = Status.PRE_DEPLOY
                self.node.od_write(entry, value)
            offset += size

    def clear_state(self):
        """Clear the rtc time and state from F-RAM; keys will be stored again after clear."""

        self._fram.clear()

        offset = 0
        for entry in FRAM_DEF:
            if entry.data_type == DataType.DOMAIN:
                continue

            if entry in [
                C3Entry.EDL_CRYPTO_KEY_0,
                C3Entry.EDL_CRYPTO_KEY_1,
                C3Entry.EDL_CRYPTO_KEY_2,
                C3Entry.EDL_CRYPTO_KEY_3,
            ]:
                raw = self.node.od_read(entry)
                raw_len = len(entry.default)
                self._fram.write(offset, raw)
            else:
                value = self.node.od_read(entry)
                raw = entry.encode(value)
                raw_len = len(raw)

            offset += raw_len

        set_rtc_time(0)
