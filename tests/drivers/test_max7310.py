import unittest

from oresat_c3.drivers.max7310 import Max7310Error, Max7310

from .. import MOCK_HW, I2C_BUS_NUM, MAX7310_ADDR


class TestMax7310(unittest.TestCase):

    def test_addresses(self):
        '''Test valid and invalid i2c addresses'''

        for addr in Max7310.ADDRESSES:
            Max7310(I2C_BUS_NUM, addr, MOCK_HW)

        for addr in [-1, 0x100, 7, 65]:
            with self.assertRaises(Max7310Error,
                                   msg=f'Max7310 obj was made with invalid addr {addr}'):
                Max7310(I2C_BUS_NUM, addr, MOCK_HW)

    def test_configure(self):

        max7310 = Max7310(I2C_BUS_NUM, MAX7310_ADDR, MOCK_HW)

        self.assertTrue(max7310.is_valid)
        self.assertFalse(max7310.is_enabled)  # False until configured

        # valid
        max7310.configure(0, 0, 4, 1)
        self.assertEqual(max7310.output_port, 0)
        self.assertEqual(max7310.polarity_inversion, 0)
        self.assertEqual(max7310.configuration, 4)
        self.assertEqual(max7310.timeout, 1)

        self.assertTrue(max7310.is_enabled)

        # invalid
        with self.assertRaises(Max7310Error):
            max7310.configure(-1, 0, 0, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, -1, 0, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, 0, -1, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, 0, 0, -1)
        with self.assertRaises(Max7310Error):
            max7310.configure(0x100, 0, 0, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, 0x100, 0, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, 0, 0x100, 0)
        with self.assertRaises(Max7310Error):
            max7310.configure(0, 0, 0, 0x100)

    def test_pin(self):

        max7310 = Max7310(I2C_BUS_NUM, MAX7310_ADDR, MOCK_HW)
        max7310.configure(0, 0, 4, 1)
        self.assertFalse(max7310.pin_status(3))
        max7310.set_pin(3)
        self.assertTrue(max7310.pin_status(3))
        max7310.clear_pin(3)
        self.assertFalse(max7310.pin_status(3))
