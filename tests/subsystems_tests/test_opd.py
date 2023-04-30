import unittest

from unittest.mock import MagicMock, patch
from oresat_c3.subsystems.opd import Opd, OpdNode, OpdError, OpdNodeState

class TestOpd(unittest.TestCase):

    def setUp(self):
        self.opd = Opd(enable_pin = 17, bus = 1, mock = True)

    def test_start(self):
        self.opd._gpio.low = MacicMock()
        self.opd.scan = MagicMock()
        self.opd.start()

        self.opd._gpio.low.assert_called_once()
