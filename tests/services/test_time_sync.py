"""Test the C3 time sync service."""

import os
import unittest
from time import time
from unittest.mock import MagicMock, patch

from olaf import CanNetwork, MasterNode, scet_int_from_time
from oresat_configs import Mission, OreSatConfig

from oresat_c3.services.node_manager import NodeState
from oresat_c3.services.time_sync import GPS_WAIT_S, RTC1_DEV, RTC1_WAIT_S, Step, TimeSyncService

GPS_STATUS_TPDO_COB_ID = 0x3B5  # GPS TPDO 7: status, number_of_sv, fix_mode, time_syncd
GPS_TIME_TPDO_COB_ID = 0x4B5  # GPS TPDO 8: scet (the time sync TPDO)

MODULE = "oresat_c3.services.time_sync"
REAL_EXISTS = os.path.exists


class FakeNodeManager:
    """Stands in for NodeManagerService: tracks the GPS's on/off state only."""

    def __init__(self, gps_status: NodeState = NodeState.OFF):
        self.gps_status = gps_status
        self.enable = MagicMock(side_effect=lambda name: self._set(NodeState.BOOT))
        self.disable = MagicMock(side_effect=lambda name: self._set(NodeState.OFF))

    def _set(self, status: NodeState) -> None:
        self.gps_status = status

    def node_status(self, name: str) -> int:
        assert name == "gps"
        return self.gps_status.value


class TestTimeSync(unittest.TestCase):
    """Test the C3 time sync service."""

    def setUp(self):
        config = OreSatConfig(Mission.default())
        self.node = MasterNode(CanNetwork("virtual", "vcan0"), config.od_db["c3"], config.od_db)
        self.node._setup_node()  # registers OLAF's SDO write callback, which calls ours
        self.node._destroy_node()

        self.node_mgr = FakeNodeManager()
        self.service = TimeSyncService(self.node_mgr)
        self.service.node = self.node
        self.service.on_start()  # registers the scet callback (without starting the thread)

        # fake hardware: whether /dev/rtc1 exists and what rtc1 reads
        self.rtc1_exists = True
        self.rtc1_time = time()

        patches = {
            "exists": patch(f"{MODULE}.os.path.exists", side_effect=self._exists),
            "geteuid": patch(f"{MODULE}.os.geteuid", return_value=0),
            "get_rtc_time": patch(f"{MODULE}.get_rtc_time", side_effect=lambda rtc: self.rtc1_time),
            "clock_settime": patch(f"{MODULE}.clock_settime"),
            "set_rtc0": patch(f"{MODULE}.set_rtc_time_to_system_time"),
            "set_rtc": patch(f"{MODULE}.set_rtc_time", return_value=True),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    def _exists(self, path: str) -> bool:
        return self.rtc1_exists if path == RTC1_DEV else REAL_EXISTS(path)

    def step(self, times: int = 1) -> None:
        """Run the service's loop body without sleeping."""
        for _ in range(times):
            self.service._run_step()

    def send_gps_status(self, time_syncd: bool) -> None:
        """Pretend the C3 received GPS TPDO 7."""
        self.node._on_pdo(GPS_STATUS_TPDO_COB_ID, bytes([2, 8, 2, int(time_syncd)]), 0.0)

    def send_gps_time(self, ts: float) -> None:
        """Pretend the C3 received the GPS time sync TPDO."""
        self.node._on_pdo(GPS_TIME_TPDO_COB_ID, scet_int_from_time(ts).to_bytes(8, "little"), 0.0)

    def assert_clock_set_to(self, ts: float) -> None:
        self.mocks["clock_settime"].assert_called_once()
        self.assertAlmostEqual(self.mocks["clock_settime"].call_args.args[1], ts, delta=0.1)
        self.mocks["set_rtc0"].assert_called_once()

    def test_rtc1_valid(self):
        """Normal boot: GPS off, rtc1 has a valid time -> clocks set from rtc1, GPS stays off."""
        self.rtc1_time = 1800000000.0
        self.step(2)
        self.assert_clock_set_to(1800000000.0)
        self.mocks["set_rtc"].assert_not_called()  # rtc1 is the source, not rewritten
        self.node_mgr.enable.assert_not_called()
        self.assertEqual(self.service._step, Step.DONE)

    def test_rtc1_invalid_uses_gps(self):
        """rtc1 lost its time -> GPS on, wait for a synced scet, set all clocks, GPS off."""
        self.rtc1_time = -1.0
        self.step(2)
        self.node_mgr.enable.assert_called_once_with("gps")
        self.assertEqual(self.service._step, Step.WAIT_GPS)

        gps_time = time() + 1000
        self.send_gps_status(time_syncd=True)
        self.send_gps_time(gps_time)
        self.step()

        self.assert_clock_set_to(gps_time)
        self.mocks["set_rtc"].assert_called_once()
        self.assertEqual(self.mocks["set_rtc"].call_args.args[1], RTC1_DEV)
        self.node_mgr.disable.assert_called_once_with("gps")
        self.assertEqual(self.service._step, Step.DONE)

    def test_rtc1_late_then_valid(self):
        """rtc1 not up yet -> keep waiting (no GPS) until it shows up."""
        self.rtc1_exists = False
        self.step(5)
        self.node_mgr.enable.assert_not_called()
        self.assertEqual(self.service._step, Step.WAIT_RTC1)

        self.rtc1_exists = True
        self.step()
        self.mocks["clock_settime"].assert_called_once()
        self.assertEqual(self.service._step, Step.DONE)

    def test_rtc1_never_shows_up(self):
        """rtc1 missing past its wait limit -> treat as broken and use the GPS."""
        self.rtc1_exists = False
        self.step(2)
        self.service._step_start -= RTC1_WAIT_S
        self.step()
        self.node_mgr.enable.assert_called_once_with("gps")
        self.assertEqual(self.service._step, Step.WAIT_GPS)

    def test_gps_unsynced_scet_ignored(self):
        """scet before the GPS has synced its clock is the GPS card's own clock -> ignore it."""
        self.rtc1_time = -1.0
        self.step(2)
        self.send_gps_status(time_syncd=False)
        self.send_gps_time(time() + 1000)
        self.step(3)
        self.mocks["clock_settime"].assert_not_called()
        self.assertEqual(self.service._step, Step.WAIT_GPS)

    def test_gps_stale_scet_ignored(self):
        """A scet received too long ago is not used."""
        self.rtc1_time = -1.0
        self.step(2)
        self.send_gps_status(time_syncd=True)
        self.send_gps_time(time() + 1000)
        gps_time, received = self.service._scet
        self.service._scet = (gps_time, received - 5)
        self.step()
        self.mocks["clock_settime"].assert_not_called()

    def test_gps_timeout(self):
        """GPS never syncs -> give up after the wait limit and turn the GPS off."""
        self.rtc1_time = -1.0
        self.step(2)
        self.service._step_start -= GPS_WAIT_S
        self.step()
        self.mocks["clock_settime"].assert_not_called()
        self.node_mgr.disable.assert_called_once_with("gps")
        self.assertEqual(self.service._step, Step.DONE)

    def test_gps_already_on(self):
        """GPS already on -> use its time, and don't turn it off (we didn't turn it on)."""
        self.node_mgr.gps_status = NodeState.ON
        self.step()
        self.assertEqual(self.service._step, Step.WAIT_GPS)

        gps_time = time() + 1000
        self.send_gps_status(time_syncd=True)
        self.send_gps_time(gps_time)
        self.step()
        self.assert_clock_set_to(gps_time)
        self.node_mgr.enable.assert_not_called()
        self.node_mgr.disable.assert_not_called()

    def test_mock_hw(self):
        """With mocked hardware, never touch the clocks."""
        self.service._mock_hw = True
        self.step(2)
        self.mocks["clock_settime"].assert_not_called()
        self.mocks["set_rtc0"].assert_not_called()
        self.assertEqual(self.service._step, Step.DONE)

    def test_errors_do_not_stop_service(self):
        """An error must not escape on_loop (OLAF would stop the service -> watchdog reset)."""
        self.node_mgr.node_status = MagicMock(side_effect=RuntimeError("boom"))
        with patch.object(self.service, "sleep"):
            self.service.on_loop()  # must not raise
        self.assertEqual(self.service._step, Step.CHECK_GPS)
