import unittest

from oresat_c3.subsystems.opd import Opd, OpdNodeState, OpdNodeId, OpdNode

from .. import I2C_BUS_NUM


class TestOpd(unittest.TestCase):

    def test_opd(self):

        opd = Opd(10, I2C_BUS_NUM, mock=True)

        for node in opd:
            if node.id in [OpdNodeId.BATTERY_1, OpdNodeId.BATTERY_2]:
                self.assertIn(node.status, [OpdNodeState.ON, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(node.status, [OpdNodeState.OFF, OpdNodeState.NOT_FOUND])

        opd.enable()

        for node in opd:
            if node.id in [OpdNodeId.BATTERY_1, OpdNodeId.BATTERY_2]:
                self.assertIn(node.status, [OpdNodeState.ON, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(node.status, [OpdNodeState.OFF, OpdNodeState.NOT_FOUND])

        opd.disable()

        for node in opd:
            self.assertEqual(node.status, OpdNodeState.OFF)

        opd._SYS_RESET_DELAY_S = 0  # just for testing lose the delay
        opd.reset()

        for node in opd:
            self.assertNotEqual(node.status, OpdNodeState.NOT_FOUND)


class TestOpdNode(unittest.TestCase):

    def test_node_enable(self):

        node = OpdNode(I2C_BUS_NUM, OpdNodeId.BATTERY_1, mock=True)
        node.configure()
        self.assertEqual(node._status, OpdNodeState.OFF)

        node.enable()
        self.assertTrue(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.ON)

        node.disable()
        self.assertFalse(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.OFF)
