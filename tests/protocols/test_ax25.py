"""Test the AX.25 protocol functions."""

import unittest

from oresat_c3.protocols.ax25 import AX25_PAYLOAD_MAX_LEN, Ax25, Ax25Error, ax25_pack, ax25_unpack


class TestAx25(unittest.TestCase):
    """Test ax25_pack and ax_25 unpack"""

    def test_ax25_roundtrip(self):
        """Test if unpack can recreate a packed packet"""
        src = Ax25(
            dest_callsign="DEST",
            dest_ssid=1,
            src_callsign="SRC",
            src_ssid=1,
            control=1,
            pid=1,
            command=True,
            response=True,
            payload=b"\x01\x02\x03",
        )
        result = ax25_unpack(
            ax25_pack(
                dest_callsign=src.dest_callsign,
                dest_ssid=src.dest_ssid,
                src_callsign=src.src_callsign,
                src_ssid=src.src_ssid,
                control=src.control,
                pid=src.pid,
                command=src.command,
                response=src.response,
                payload=src.payload,
            )
        )
        self.assertEqual(src, result)

    def test_ax25_pack_invalid_dest_callsign_length(self):
        """Set destination callsign with a length greater than AX25_CALLSIGN_LEN"""

        # Check if Ax25Error is raised for the invalid destination callsign length
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="INVAID_CALLSIGN",
                dest_ssid=1,
                src_callsign="SRC",
                src_ssid=1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_dest_ssid_large(self):
        """Set destination ssid greater than 15"""

        # Check if Ax25Error is raised for the invalid destination ssid value
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=0x100,
                src_callsign="SRC",
                src_ssid=1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_dest_ssid_small(self):
        """Set destination ssid less than 0"""

        # Check if Ax25Error is raised for the invalid destination ssid value
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=-1,
                src_callsign="SRC",
                src_ssid=1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_src_callsign(self):
        """Set source callsign with a length greater than AX25_CALLSIGN_LEN"""

        # Check if Ax25Error is raised for the invalid source callsign length
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=1,
                src_callsign="INVALID_CALLSIGN",
                src_ssid=1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_src_ssid_larger(self):
        """Set source ssid to be greater than 15"""

        # Check if Ax25Error is raised for the invalid invalid source ssid value
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=1,
                src_callsign="SRC",
                src_ssid=0x100,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_src_ssid_small(self):
        """Set source ssid with to be less than 0"""

        # Check if Ax25Error is raised for the invalid source ssid value
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=1,
                src_callsign="SRC",
                src_ssid=-1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x01\x02\x03",
            )

    def test_ax25_pack_invalid_payload(self):
        """Set payload with a length greater than AX25_PAYLOAD_MAX_LEN"""

        # Check if Ax25Error is raised for the invalid source ssid value
        with self.assertRaises(Ax25Error):
            ax25_pack(
                dest_callsign="DEST",
                dest_ssid=1,
                src_callsign="SRC",
                src_ssid=1,
                control=1,
                pid=1,
                command=True,
                response=True,
                payload=b"\x00" * (AX25_PAYLOAD_MAX_LEN + 1),
            )
