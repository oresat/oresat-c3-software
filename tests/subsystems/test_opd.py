"""Unit test for the Opd and OpdNode classes."""

import unittest

from oresat_c3.subsystems.opd import Opd, OpdNode, OpdNodeState

from .. import I2C_BUS_NUM


class TestOpd(unittest.TestCase):
    """Test the Opd subsystem."""

    def test_opd(self):
        """Test enable/disable works."""

        opd = Opd(10, 12, 2, mock=True)

        for node in opd:
            if node.name in ["battery_1", "battery_2"]:
                self.assertIn(node.status, [OpdNodeState.ENABLED, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(node.status, [OpdNodeState.DISABLED, OpdNodeState.NOT_FOUND])

        opd.enable()

        for node in opd:
            if node.name in ["battery_1", "battery_2"]:
                self.assertIn(node.status, [OpdNodeState.ENABLED, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(node.status, [OpdNodeState.DISABLED, OpdNodeState.NOT_FOUND])

        opd.disable()

        for node in opd:
            self.assertEqual(node.status, OpdNodeState.DISABLED)

        opd._SYS_RESET_DELAY_S = 0  # just for testing lose the delay
        opd.reset()

        for node in opd:
            self.assertNotEqual(node.status, OpdNodeState.NOT_FOUND)


class TestOpdNode(unittest.TestCase):
    """Test the Opd node class."""

    def test_node_enable(self):
        """Test enable/disable works."""
        node = OpdNode(I2C_BUS_NUM, "battery_1", 0x18, mock=True)
        node.configure()
        self.assertEqual(node._status, OpdNodeState.DISABLED)

        node.enable()
        self.assertTrue(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.ENABLED)

        node.disable()
        self.assertFalse(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.DISABLED)
