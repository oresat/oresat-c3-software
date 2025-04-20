import unittest
from time import time

from oresat_canopend import NodeClient

from oresat_c3.gen.c3_od import C3Entry, C3Status, C3SystemReset
from oresat_c3.services.state import StateService


class TestState(unittest.TestCase):
    def setUp(self):
        self.node = NodeClient(C3Entry)
        self.service = StateService(self.node, mock_hw=True)

        # initial the service, but stop the thread
        self.service._event.set()
        self.service.start()
        self.service.stop()

    def test_pre_deploy(self):
        """Test state transistion(s) from PRE_DEPLOY state"""

        # initial state for this test
        self.node.od_write(C3Entry.STATUS, C3Status.PRE_DEPLOY)
        self.node.od_write(C3Entry.TX_CONTROL_ENABLE, False)

        # test PRE_DEPLOY -> PRE_DEPLOY
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.PRE_DEPLOY)
        self.service._pre_deploy()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.PRE_DEPLOY)
        self.assertTrue(self.node.od_read(C3Entry.TX_CONTROL_ENABLE))

        # test PRE_DEPLOY -> DEPLOY; timeout has ended
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.PRE_DEPLOY)
        self.node.od_write(C3Entry.ANTENNAS_PRE_ATTEMPT_TIMEOUT, 0)
        self.service._pre_deploy()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)

    def test_deploy(self):
        """Test state transistion(s) from DEPLOY state"""

        # initial state for this test
        self.node.od_write(C3Entry.STATUS, C3Status.DEPLOY)

        # test DEPLOY -> DEPLOY; battery level is too low for deployment
        self.node.od_write(C3Entry.BATTERY_1_PACK_1_VBATT, StateService.BAT_LEVEL_LOW_MV - 1)
        self.node.od_write(C3Entry.BATTERY_1_PACK_2_VBATT, StateService.BAT_LEVEL_LOW_MV - 1)
        for _ in range(10):
            self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)
            self.service._deploy()

        # speed up tests
        self.node.od_write_multi(
            {
                C3Entry.ANTENNAS_PRE_ATTEMPT_TIMEOUT: 0,
                C3Entry.TX_CONTROL_ENABLE: True,
                C3Entry.ANTENNAS_ATTEMPT_TIMEOUT: 0,
                C3Entry.ANTENNAS_REATTEMPT_TIMEOUT: 0,
                C3Entry.ANTENNAS_ATTEMPT_BETWEEN_TIMEOUT: 0,
            }
        )

        # test DEPLOY -> STANDBY; good battery level
        self.node.od_write(C3Entry.BATTERY_1_PACK_1_VBATT, StateService.BAT_LEVEL_LOW_MV + 1)
        self.node.od_write(C3Entry.BATTERY_1_PACK_2_VBATT, StateService.BAT_LEVEL_LOW_MV + 1)
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)
        self.service._deploy()  # attempt 0
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)
        self.service._deploy()  # attempt 1
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)
        self.service._deploy()  # attempt 2
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.DEPLOY)
        self.service._deploy()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

    def test_standby(self):
        """Test state transistion(s) from STANDBY state"""

        # initial state for this test
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.STANDBY,
                C3Entry.TX_CONTROL_ENABLE: False,
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV - 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV - 1,
            }
        )
        self.node._reset = C3SystemReset.SOFT_RESET
        self.node.od_write(C3Entry.EDL_LAST_TIMESTAMP, 0)

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx disabled
        self.service._standby()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

        # test STANDBY -> STANDBY; battery level is too low for deployment and tx enabled
        self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, int(time()))
        self.service._standby()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

        # test STANDBY -> STANDBY; battery level is good for deployment and tx disabled
        self.node.od_write_multi(
            {
                C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP: 0,
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
            }
        )
        self.service._standby()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

        # test STANDBY -> BEACON; battery level is good for deployment and tx enabled
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.STANDBY,
                C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP: int(time()),
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
            }
        )
        self.service._standby()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.BEACON)

        # test STANDBY -> EDL; EDL is received
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.STANDBY,
                C3Entry.EDL_LAST_TIMESTAMP: int(time()),
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
            }
        )
        self.service._standby()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.EDL)

    def test_beacon(self):
        """Test state transistion(s) from BEACON state"""

        # initial state for this test
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.BEACON,
                C3Entry.EDL_LAST_TIMESTAMP: 0,
                C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP: int(time()),
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
            }
        )

        # test BEACON -> BEACON; battery level is good and tx enabled
        self.service._beacon()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.BEACON)

        # test BEACON -> STANDBY; battery level is good and tx disabled
        self.node.od_write(C3Entry.STATUS, C3Status.BEACON)
        self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, 0)
        self.service._beacon()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

        # test BEACON -> EDL; EDL is received
        self.node.od_write(C3Entry.STATUS, C3Status.BEACON)
        self.node.od_write(C3Entry.EDL_LAST_TIMESTAMP, int(time()))
        self.service._beacon()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.EDL)

    def test_edl(self):
        """Test state transistion(s) from EDL state"""

        # initial state for this test
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.EDL,
                C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP: int(time()),
                C3Entry.EDL_LAST_TIMESTAMP: int(time()),
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV + 1,
            }
        )

        # test EDL -> EDL; not timeout
        self.service._edl()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.EDL)

        # test EDL -> BEACON; timed out, battery level is good and tx enabled
        self.node.od_write(C3Entry.EDL_LAST_TIMESTAMP, 0)
        self.service._edl()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.BEACON)

        # test EDL -> STANDBY; timed out, battery level is good and tx disabled
        self.node.od_write(C3Entry.STATUS, C3Status.EDL)
        self.node.od_write(C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP, 0)
        self.service._edl()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)

        # test EDL -> STANDBY; battery level is too low and tx enabled
        self.node.od_write_multi(
            {
                C3Entry.STATUS: C3Status.EDL,
                C3Entry.TX_CONTROL_LAST_ENABLE_TIMESTAMP: int(time()),
                C3Entry.BATTERY_1_PACK_1_VBATT: StateService.BAT_LEVEL_LOW_MV - 1,
                C3Entry.BATTERY_1_PACK_2_VBATT: StateService.BAT_LEVEL_LOW_MV - 1,
            }
        )
        self.service._edl()
        self.assertEqual(self.node.od_read(C3Entry.STATUS), C3Status.STANDBY)
