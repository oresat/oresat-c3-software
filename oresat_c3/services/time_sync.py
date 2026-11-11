"""Time sync service.

Sets the C3's clocks at boot:

- If the GPS is already on, use the GPS time.
- Otherwise, if the external RTC (rtc1, the RV-3028 on the backup capacitor) has a valid time, use
  that. This is the normal boot.
- Otherwise (first boot, or powered off long enough for the capacitor to run out), turn on the GPS,
  wait for it to sync its clock to GPS time, and use the GPS time. Turn the GPS back off afterwards
  if this service turned it on.

The GPS time comes from the GPS card's time sync TPDO (``[scet]`` in oresat-configs gps.yaml). It
is only used once the GPS card reports ``time_syncd`` (GPS TPDO 7), because before that the scet is
just the GPS card's own unsynced clock.

"Setting the clocks" means the C3's system clock (what all C3 software reads) and rtc0 (the
Octavo's internal RTC). rtc1 is also set when the time comes from the GPS.
"""

import os
from datetime import datetime, timezone
from enum import Enum, auto
from time import CLOCK_REALTIME, clock_settime, monotonic, time

from olaf import Service, logger, scet_int_to_time

from ..subsystems.rtc import get_rtc_time, set_rtc_time, set_rtc_time_to_system_time
from .node_manager import NodeManagerService, NodeState

RTC1 = "rtc1"
"""The external RTC (RV-3028), the only clock that keeps time across a power loss."""

RTC1_DEV = f"/dev/{RTC1}"

RTC1_WAIT_S = 60
"""How long to wait for rtc1 to show up (the I2C bus comes up late in boot). Safety check only."""

GPS_WAIT_S = 15 * 60
"""How long to wait for the GPS to sync before giving up and turning it off (to save power)."""

SCET_MAX_AGE_S = 2
"""Only use a scet received within this many seconds (the GPS sends one every second)."""

MIN_VALID_TIME = 1767225600
"""2026-01-01 00:00:00 UTC. Any clock earlier than this is treated as not valid."""


class Step(Enum):
    """The steps of the time sync flow."""

    CHECK_GPS = auto()
    """Is the GPS on?"""
    WAIT_RTC1 = auto()
    """Is rtc1 (I2C) on? Is rtc1's time valid?"""
    WAIT_GPS = auto()
    """Wait for the GPS to sync and send scet."""
    DONE = auto()
    """Nothing left to do (the service keeps running, so the watchdog doesn't see it as failed)."""


class TimeSyncService(Service):
    """Set the C3's clocks from rtc1 or the GPS at boot."""

    def __init__(self, node_mgr: NodeManagerService, mock_hw: bool = False):
        super().__init__()
        self._node_mgr = node_mgr
        self._mock_hw = mock_hw
        self._step = Step.CHECK_GPS
        self._step_start = monotonic()
        self._we_enabled_gps = False
        self._scet: tuple[float, float] | None = None  # (GPS time, monotonic() when received)

    def on_start(self) -> None:
        self.node.add_sdo_callbacks("gps", "scet", None, self._on_gps_scet)

    def _on_gps_scet(self, value: int) -> None:
        """SDO write callback, called each time the GPS time sync TPDO is received."""

        self._scet = (scet_int_to_time(value), monotonic())

    def on_loop(self) -> None:
        # Never let an exception escape: OLAF would stop this service and in flight mode the C3
        # would stop petting the watchdog, resetting the satellite.
        try:
            self._run_step()
        except Exception as e:  # pylint: disable=W0718
            logger.exception(f"time sync error in step {self._step.name}: {e}")

        self.sleep(1 if self._step != Step.DONE else 10)

    def _run_step(self) -> None:
        if self._step == Step.CHECK_GPS:
            self._check_gps()
        elif self._step == Step.WAIT_RTC1:
            self._wait_rtc1()
        elif self._step == Step.WAIT_GPS:
            self._wait_gps()

    def _go_to(self, step: Step) -> None:
        logger.debug(f"time sync: {self._step.name} -> {step.name}")
        self._step = step
        self._step_start = monotonic()

    def _check_gps(self) -> None:
        """Is the GPS on?"""

        status = NodeState(self._node_mgr.node_status("gps"))
        if status in (NodeState.BOOT, NodeState.ON):
            logger.info("time sync: GPS is already on, waiting for GPS time")
            self._go_to(Step.WAIT_GPS)
        else:
            self._go_to(Step.WAIT_RTC1)

    def _wait_rtc1(self) -> None:
        """Is rtc1 (I2C) on? If so, is its time valid?"""

        if not os.path.exists(RTC1_DEV):
            if monotonic() - self._step_start < RTC1_WAIT_S:
                return  # not up yet, check again next loop
            logger.error(f"time sync: {RTC1} never showed up, using GPS time instead")
            self._turn_on_gps()
            return

        ts = get_rtc_time(RTC1)
        if ts < MIN_VALID_TIME:
            logger.info(f"time sync: {RTC1} has no valid time, using GPS time instead")
            self._turn_on_gps()
            return

        self._set_clocks(ts, RTC1, set_rtc1=False)
        self._go_to(Step.DONE)

    def _turn_on_gps(self) -> None:
        # Forget any time_syncd value from an earlier GPS session until the GPS sends a new one.
        self.node.od["gps"]["time_syncd"].value = False
        self._scet = None
        self._node_mgr.enable("gps")
        self._we_enabled_gps = True
        logger.info("time sync: turned on GPS, waiting for GPS time")
        self._go_to(Step.WAIT_GPS)

    def _wait_gps(self) -> None:
        """Wait for the GPS to sync and send scet."""

        synced = self.node.od["gps"]["time_syncd"].value
        scet = self._scet
        if synced and scet is not None and monotonic() - scet[1] <= SCET_MAX_AGE_S:
            gps_time, received = scet
            # Add the time since the scet was received, so the delay before this loop ran doesn't
            # make the clock late.
            self._set_clocks(gps_time + (monotonic() - received), "GPS", set_rtc1=True)
            self._finish_gps()
        elif monotonic() - self._step_start >= GPS_WAIT_S:
            logger.error(f"time sync: GPS did not sync in {GPS_WAIT_S // 60} min, giving up")
            self._finish_gps()

    def _finish_gps(self) -> None:
        if self._we_enabled_gps:
            self._node_mgr.disable("gps")
            self._we_enabled_gps = False
            logger.info("time sync: turned off GPS")
        self._go_to(Step.DONE)

    def _set_clocks(self, ts: float, source: str, set_rtc1: bool) -> None:
        """Set the system clock and rtc0 (and optionally rtc1) to ts."""

        utc = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        if self._mock_hw:
            logger.info(f"time sync: mocking hardware, not setting clocks to {utc} from {source}")
            return
        if os.geteuid() != 0:
            logger.error("time sync: cannot set clocks, not running as root")
            return

        clock_settime(CLOCK_REALTIME, ts)
        set_rtc_time_to_system_time()  # rtc0
        clocks = "system, rtc0"
        if set_rtc1 and os.path.exists(RTC1_DEV) and set_rtc_time(time(), RTC1_DEV):
            clocks += f", {RTC1}"

        logger.info(f"time set from {source}: {utc} ({clocks})")
