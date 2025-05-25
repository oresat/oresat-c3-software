"""Unit test for the Opd and OpdNode classes."""

import unittest

from oresat_c3.gen.cards import Card, CardProcessor
from oresat_c3.subsystems.opd import (
    Opd,
    OpdNode,
    OpdNodeState,
    OpdOctavoNode,
    OpdState,
    OpdStm32Node,
)

from .. import I2C_BUS_NUM


class TestOpd(unittest.TestCase):
    """Test the Opd subsystem."""

    def test_opd(self):
        """Test enable/disable works."""

        mock_hw = True
        opd = Opd("gpio1", "gpio2", 2, mock=mock_hw)

        # add cards
        for card in Card:
            if card.opd_address == 0:
                continue  # not an opd node

            opd_node = None
            if card.processor == CardProcessor.NONE:
                opd_node = OpdNode(0, card.name, card.opd_address, mock_hw)
            elif card.processor == CardProcessor.STM32:
                opd_node = OpdStm32Node(0, card.name, card.opd_address, mock_hw)
            elif card.processor == CardProcessor.OCTAVO:
                opd_node = OpdOctavoNode(0, card.name, card.opd_address, mock_hw)

            self.assertIsNotNone(opd_node)
            opd[card.opd_address] = opd_node

        for card in Card:
            if card.opd_address == 0:
                continue

            status = opd[card.opd_address].status
            if card.opd_always_on:
                self.assertIn(status, [OpdNodeState.ENABLED, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(status, [OpdNodeState.DISABLED, OpdNodeState.NOT_FOUND])

        opd.enable()
        self.assertEqual(opd.status, OpdState.ENABLED)

        for card in Card:
            if card.opd_address == 0:
                continue

            status = opd[card.opd_address].status
            if card.opd_always_on:
                self.assertIn(status, [OpdNodeState.ENABLED, OpdNodeState.NOT_FOUND])
            else:
                self.assertIn(status, [OpdNodeState.DISABLED, OpdNodeState.NOT_FOUND])

        opd.disable()
        self.assertEqual(opd.status, OpdState.DISABLED)

        opd.reset(1, 0)

        for card in Card:
            status = opd[card.opd_address].status
            self.assertNotEqual(status, OpdNodeState.NOT_FOUND)


class TestOpdNode(unittest.TestCase):
    """Test the Opd node class."""

    def test_node_enable(self):
        """Test enable/disable works."""
        card = Card.BATTERY_1
        node = OpdNode(I2C_BUS_NUM, card.name, card.opd_address, mock=True)
        node.configure()
        self.assertEqual(node._status, OpdNodeState.DISABLED)

        node.enable()
        self.assertTrue(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.ENABLED)

        node.disable()
        self.assertFalse(node.is_enabled)
        self.assertEqual(node._status, OpdNodeState.DISABLED)
