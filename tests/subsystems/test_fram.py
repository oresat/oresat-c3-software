import os
import unittest

from oresat_c3.drivers.fm24cl64b import Fm24cl64b
from oresat_c3.subsystems.fram import FramKey, Fram, FramError

from .. import MOCK_HW, I2C_BUS_NUM, FRAM_ADDR


class TestFram(unittest.TestCase):

    def setUp(self):

        if os.path.isfile(Fm24cl64b._MOCK_FILE):
            os.remove(Fm24cl64b._MOCK_FILE)

    def tearDown(self):

        if os.path.isfile(Fm24cl64b._MOCK_FILE):
            os.remove(Fm24cl64b._MOCK_FILE)

    def test_entries(self):

        fram = Fram(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        with self.assertRaises(FramError):  # cannot add new entries dynamically
            fram._add_entry(FramKey.C3_STATE, 'I')

    def test_read(self):

        fram = Fram(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        for key in list(FramKey):
            self.assertIsNotNone(fram[key], f'{key.name} read got None as data')

        with self.assertRaises(FramError):
            fram['invalid-key']

        self.assertEqual(len(fram.get_all()), len(list(FramKey)))

    def test_write(self):

        fram = Fram(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        for key in list(FramKey):
            if key == FramKey.CRYTO_KEY:
                data = bytes([0xAA] * 128)
                bad_data = 10
            elif key == FramKey.DEPLOYED:
                data = True
                bad_data = 'abc'
            else:  # everything else is a int
                data = 10
                bad_data = 'abc'

            fram[key] = data

            self.assertEqual(fram[key], data,
                             f'{key.name} write then read mismatch {fram[key]} vs {data}')

            with self.assertRaises(FramError, msg=f'{key.name} write with bad data worked'):
                fram[key] = bad_data

            # should still be the same value
            self.assertEqual(fram[key], data,
                             f'{key.name} was able to write bad data with no error')
