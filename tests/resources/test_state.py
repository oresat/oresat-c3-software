import unittest
from os.path import abspath, dirname
from time import time

import canopen
from olaf import MasterNode, NodeStop
from oresat_c3 import C3State
from oresat_c3.subsystems.fram import Fram
from oresat_c3.resources.state import StateResource


class TestState(unittest.TestCase):

    def setUp(self):

        eds = abspath(dirname(__file__)) + '/../../oresat_c3/data/oresat_c3.dcf'
        self.od = canopen.objectdictionary.eds.import_eds(eds, 0x10)
        self.node = MasterNode(self.od, 'vcan0')

        fram = Fram(2, 0x50, True)
        self.res = StateResource(fram)

        self.node._setup_node()
        self.node._destroy_node()

        # initial the resource, but stop the thread
        self.res._event.set()
        self.res.start(self.node)
        self.res.end()

    def test_pre_deploy(self):
        '''Test state transistion(s) from PRE_DEPLOY state'''

        # initial state for this test
        self.res._c3_state_obj.value = C3State.PRE_DEPLOY.value
        self.res._tx_enabled_obj.value = False

        # test PRE_DEPLOY -> PRE_DEPLOY
        self.assertEqual(self.res._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.res._pre_deploy()
        self.assertEqual(self.res._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.assertTrue(self.res._tx_enabled_obj.value)

        # test PRE_DEPLOY -> DEPLOY; timeout has ended
        self.res._boot_time = 0
        self.assertEqual(self.res._c3_state_obj.value, C3State.PRE_DEPLOY)
        self.res._pre_deploy()
        self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)

    def test_deploy(self):
        '''Test state transistion(s) from DEPLOY state'''

        # initial state for this test
        self.res._c3_state_obj.value = C3State.DEPLOY.value

        # test DEPLOY -> DEPLOY; battery level is too low for deployment
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW - 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW - 1
        for i in range(10):
            self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)
            self.res._deploy()

        # test DEPLOY -> STANDBY; good battery level
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)
        self.res._deploy()  # attempt 0
        self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)
        self.res._deploy()  # attempt 1
        self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)
        self.res._deploy()  # attempt 2
        self.assertEqual(self.res._c3_state_obj.value, C3State.DEPLOY)
        self.res._deploy()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)

    def test_standby(self):
        '''Test state transistion(s) from STANDBY state'''

        # initial state for this test
        self.res._c3_state_obj.value = C3State.STANDBY.value
        self.res._last_tx_enable_obj.value = 0
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW - 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW - 1
        self.node._reset = NodeStop.SOFT_RESET

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx disabled
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx enabled
        self.res._last_tx_enable_obj.value = time()
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> STANDBY; battery level is good for deployment and tx disabled
        self.res._last_tx_enable_obj.value = 0
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> BEACON; battery level is good for deployment and tx enabled
        self.res._c3_state_obj.value = C3State.STANDBY
        self.res._last_tx_enable_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY -> EDL; EDL is received
        self.res._c3_state_obj.value = C3State.STANDBY
        self.res._last_edl_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test STANDBY hard reset
        self.res._c3_state_obj.value = C3State.STANDBY
        self.res._last_edl_obj.value = 0
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)
        self.res._boot_time = 0
        self.res._standby()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.HARD_RESET)

    def test_beacon(self):
        '''Test state transistion(s) from BEACON state'''

        # initial state for this test
        self.node._reset = NodeStop.SOFT_RESET
        self.res._c3_state_obj.value = C3State.BEACON.value
        self.res._last_tx_enable_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.node._reset = NodeStop.SOFT_RESET

        # test BEACON -> BEACON; battery level is good and tx enabled
        self.res._beacon()
        self.assertEqual(self.res._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test BEACON -> BEACON; battery level is good and tx disabled
        self.res._last_tx_enable_obj.value = 0
        self.res._beacon()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test BEACON -> EDL; EDL is received
        self.res._c3_state_obj.value = C3State.BEACON
        self.res._last_edl_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._beacon()
        self.assertEqual(self.res._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test BEACON hard reset
        self.res._c3_state_obj.value = C3State.BEACON
        self.res._last_edl_obj.value = 0
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)
        self.res._boot_time = 0
        self.res._beacon()
        self.assertEqual(self.res._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.HARD_RESET)

    def test_edl(self):
        '''Test state transistion(s) from EDL state'''

        # initial state for this test
        self.node._reset = NodeStop.SOFT_RESET
        self.res._c3_state_obj.value = C3State.EDL.value
        self.res._last_tx_enable_obj.value = time()
        self.res._last_edl_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW + 1
        self.node._reset = NodeStop.SOFT_RESET

        # test EDL -> EDL; not timeout
        self.res._edl()
        self.assertEqual(self.res._c3_state_obj.value, C3State.EDL)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> BEACON; battery level is good and tx enabled
        self.res._last_edl_obj.value = 0
        self.res._last_tx_enable_obj.value = time()
        self.res._edl()
        self.assertEqual(self.res._c3_state_obj.value, C3State.BEACON)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> STANDBY; battery level is good and tx disabled
        self.res._last_edl_obj.value = 0
        self.res._last_tx_enable_obj.value = 0
        self.res._edl()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)

        # test EDL -> STANDBY; battery level is too low and tx enabled
        self.res._last_edl_obj.value = 0
        self.res._last_tx_enable_obj.value = time()
        self.res._vbatt_bp1_obj.value = StateResource.BAT_LEVEL_LOW - 1
        self.res._vbatt_bp2_obj.value = StateResource.BAT_LEVEL_LOW - 1
        self.res._edl()
        self.assertEqual(self.res._c3_state_obj.value, C3State.STANDBY)
        self.assertEqual(self.node._reset, NodeStop.SOFT_RESET)
