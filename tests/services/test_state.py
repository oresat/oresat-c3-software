"""Test the C3 state service."""

import unittest
from time import time

from olaf import CanNetwork, MasterNode, NodeStop
from oresat_configs import OreSatConfig, OreSatId

from oresat_c3 import C3State
from oresat_c3.services.state import StateService


class TestState(unittest.TestCase):
    """Test the C3 state service."""

    def setUp(self):
        config = OreSatConfig(OreSatId.ORESAT0_5)
        self.od = config.od_db["c3"]
        fram_def = config.fram_def
        network = CanNetwork("virtual", "vcan0")
        self.node = MasterNode(network, self.od, config.od_db)

        self.service = StateService(fram_def, mock_hw=True)

        self.node._setup_node()
        self.node._destroy_node()

        # initial the service, but stop the thread
        self.service._event.set()
        self.service.start(self.node)
        self.service.stop()

    def test_pre_deploy(self):
        """Test state transistion(s) from PRE_DEPLOY state"""

        # initial state for this test
        self.service._c3_state_obj.value = C3State.PRE_DEPLOY.value
        self.service._tx_enable_obj.value = False

        # test PRE_DEPLOY -> PRE_DEPLOY
        self.assertEqual(self.service._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.service._pre_deploy()
        self.assertEqual(self.service._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.assertTrue(self.service._tx_enable_obj.value)

        # test PRE_DEPLOY -> DEPLOY; timeout has ended
        self.assertEqual(self.service._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.service._pre_deploy_timeout_obj.value = 0.0
        self.service._pre_deploy()
        self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)

    def test_deploy(self):
        """Test state transistion(s) from DEPLOY state"""

        # initial state for this test
        self.service._c3_state_obj.value = C3State.DEPLOY.value

        # test DEPLOY -> DEPLOY; battery level is too low for deployment
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW - 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW - 1
        for _ in range(10):
            self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)
            self.service._deploy()

        # speed up tests
        self.service._ant_attempt_timeout_obj.value = 0
        self.service._tx_enable_obj.value = True
        self.service._ant_reattempt_timeout_obj.value = 0
        self.service._ant_attempt_between_timeout_obj.value = 0

        # test DEPLOY -> STANDBY; good battery level
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)
        self.service._deploy()  # attempt 0
        self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)
        self.service._deploy()  # attempt 1
        self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)
        self.service._deploy()  # attempt 2
        self.assertEqual(self.service._c3_state_obj.value, C3State.DEPLOY)
        self.service._deploy()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)

    def test_standby(self):
        """Test state transistion(s) from STANDBY state"""

        # initial state for this test
        self.service._c3_state_obj.value = C3State.STANDBY.value
        self.service._last_tx_enable_obj.value = 0
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW - 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW - 1
        self.node._reset = NodeStop.SOFT_RESET
        self.service._last_edl_obj.value = 0

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx disabled
        self.service._standby()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx enabled
        self.service._last_tx_enable_obj.value = int(time())
        self.service._standby()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> STANDBY; battery level is good for deployment and tx disabled
        self.service._last_tx_enable_obj.value = 0
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._standby()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> BEACON; battery level is good for deployment and tx enabled
        self.service._c3_state_obj.value = C3State.STANDBY
        self.service._last_tx_enable_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._standby()
        self.assertEqual(self.service._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> EDL; EDL is received
        self.service._c3_state_obj.value = C3State.STANDBY
        self.service._last_edl_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._standby()
        self.assertEqual(self.service._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

    def test_beacon(self):
        """Test state transistion(s) from BEACON state"""

        # initial state for this test
        self.node._reset = NodeStop.SOFT_RESET
        self.service._c3_state_obj.value = C3State.BEACON.value
        self.service._last_tx_enable_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.node._reset = NodeStop.SOFT_RESET

        # test BEACON -> BEACON; battery level is good and tx enabled
        self.service._beacon()
        self.assertEqual(self.service._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test BEACON -> BEACON; battery level is good and tx disabled
        self.service._last_tx_enable_obj.value = 0
        self.service._beacon()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test BEACON -> EDL; EDL is received
        self.service._c3_state_obj.value = C3State.BEACON
        self.service._last_edl_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._beacon()
        self.assertEqual(self.service._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

    def test_edl(self):
        """Test state transistion(s) from EDL state"""

        # initial state for this test
        self.node._reset = NodeStop.SOFT_RESET
        self.service._c3_state_obj.value = C3State.EDL.value
        self.service._last_tx_enable_obj.value = int(time())
        self.service._last_edl_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW + 1
        self.node._reset = NodeStop.SOFT_RESET

        # test EDL -> EDL; not timeout
        self.service._edl()
        self.assertEqual(self.service._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> BEACON; battery level is good and tx enabled
        self.service._last_edl_obj.value = 0
        self.service._last_tx_enable_obj.value = int(time())
        self.service._edl()
        self.assertEqual(self.service._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> STANDBY; battery level is good and tx disabled
        self.service._last_edl_obj.value = 0
        self.service._last_tx_enable_obj.value = 0
        self.service._edl()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> STANDBY; battery level is too low and tx enabled
        self.service._last_edl_obj.value = 0
        self.service._last_tx_enable_obj.value = int(time())
        self.service._vbatt_bp1_obj.value = StateService.BAT_LEVEL_LOW - 1
        self.service._vbatt_bp2_obj.value = StateService.BAT_LEVEL_LOW - 1
        self.service._edl()
        self.assertEqual(self.service._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)
