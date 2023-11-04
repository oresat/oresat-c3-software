"""Unit tests for the FM23CL64B driver."""

import os
import unittest

from oresat_c3.drivers.fm24cl64b import Fm24cl64b, Fm24cl64bError

from .. import FRAM_ADDR, I2C_BUS_NUM, MOCK_HW


class TestFm24cl64b(unittest.TestCase):
    """Test the Fm24cl64b driver."""

    def setUp(self):
        if os.path.isfile(Fm24cl64b.MOCK_FILE):
            os.remove(Fm24cl64b.MOCK_FILE)

    def tearDown(self):
        if os.path.isfile(Fm24cl64b.MOCK_FILE):
            os.remove(Fm24cl64b.MOCK_FILE)

    def test_addresses(self):
        """Test valid and invalid i2c addresses"""

        for addr in Fm24cl64b.ADDRESSES:
            Fm24cl64b(I2C_BUS_NUM, addr, MOCK_HW)

        for addr in [-1, 0x100, 0x49, 0x60]:
            with self.assertRaises(
                Fm24cl64bError, msg=f"Fm24cl64b obj was made with invalid addr {addr}"
            ):
                Fm24cl64b(I2C_BUS_NUM, addr, MOCK_HW)

    def test_read(self):
        """Test reading from fram."""

        fram = Fm24cl64b(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        # valid
        self.assertEqual(len(fram.read(0, 10)), 10)
        self.assertEqual(len(fram.read(40, 1)), 1)
        self.assertEqual(len(fram.read(40, 1000)), 1000)
        self.assertIn(type(fram.read(0, 10)), [bytes, bytearray])

        # invalid
        with self.assertRaises(Fm24cl64bError):
            fram.read(7500, 1000)  # F-RAM only has 8KB
        with self.assertRaises(Fm24cl64bError):
            fram.read(-1, 10)  # cannot do negative offsets
        with self.assertRaises(Fm24cl64bError):
            fram.read(0, 0)  # size must be greater than 1
        with self.assertRaises(Fm24cl64bError):
            fram.read(0, -1)  # size must be greater than 1

    def test_write(self):
        """Test writeing to fram."""

        fram = Fm24cl64b(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        # valid, should raise no errors
        fram.write(0, bytes([1] * 5))
        fram.write(0, bytearray([0] * 25))

        # invalid
        with self.assertRaises(Fm24cl64bError):
            fram.write(0, 10)  # invalid data type
        with self.assertRaises(Fm24cl64bError):
            fram.write(0, [1] * 5)  # invalid data type
        with self.assertRaises(Fm24cl64bError):
            fram.write(0, "abc")  # invalid data type
        with self.assertRaises(Fm24cl64bError):
            fram.write(7500, bytes([0] * 1000))  # F-RAM only has 8KB
        with self.assertRaises(Fm24cl64bError):
            fram.write(-1, b"\x10")  # cannot do negative offsets
        with self.assertRaises(Fm24cl64bError):
            fram.write(0, b"")  # no data

    def test_read_write(self):
        """Test reads and writes work."""

        fram = Fm24cl64b(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        # make sure data is actually written
        data = bytes([0xAA] * 10)
        offset = 0
        fram.write(offset, data)
        self.assertEqual(fram.read(offset, len(data)), data)

        # overwrite a couple bytes
        new_bytes = b"\x12\x34"
        offset = 1
        tmp = bytearray(data)
        tmp[offset : offset + len(new_bytes)] = new_bytes
        new_data = bytes(tmp)
        fram.write(offset, new_bytes)
        self.assertEqual(fram.read(offset, len(new_bytes)), new_bytes)
        self.assertEqual(fram.read(0, len(new_data)), new_data)

    def test_reload(self):
        """Test on a remake of of the Fm24cl64b obj the data still exist."""

        data = bytes([1] * 5)
        offset = 0

        fram = Fm24cl64b(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        fram.write(offset, data)
        self.assertEqual(fram.read(offset, len(data)), data)

        # remake obj
        fram = Fm24cl64b(I2C_BUS_NUM, FRAM_ADDR, MOCK_HW)

        self.assertEqual(fram.read(offset, len(data)), data)
