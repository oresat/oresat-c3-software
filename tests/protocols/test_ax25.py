import unittest

from oresat_c3.protocols.ax25 import generate_ax25_packet, AX25_PAYLOAD_MAX_LEN, Ax25Error

class TestAx25(unittest.TestCase):

    def test_generate_ax25_invalid_dest_callsign_length(self):
        #Set destination callsign with a length greater than AX25_CALLSIGN_LEN
        invalid_dest_callsign = 'INVAID_CALLSIGN'
        dest_ssid = 1
        src_callsign = 'SRC'
        src_ssid = 1
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid destination callsign length
        with self.assertRaises(Ax25Error):
            generate_ax25_packet(invalid_dest_callsign, dest_ssid, src_callsign, src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_dest_ssid_large(self):
        #Set destination ssid greater than 15
        dest_callsign = 'DEST'
        invalid_dest_ssid = 16
        src_callsign = 'SRC'
        src_ssid = 1
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid destination ssid value
        with self.assertRaisesRegex(Ax25Error, 'dest_ssid must be between 0 and 15'):
            generate_ax25_packet(dest_callsign, invalid_dest_ssid, src_callsign, src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_dest_ssid_small(self):
        #Set destination ssid less than 0
        dest_callsign = 'DEST'
        invalid_dest_ssid = -1
        src_callsign = 'SRC'
        src_ssid = 1
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid destination ssid value
        with self.assertRaisesRegex(Ax25Error, 'dest_ssid must be between 0 and 15'):
            generate_ax25_packet(dest_callsign, invalid_dest_ssid, src_callsign, src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_src_callsign(self):
        #Set source callsign with a length greater than AX25_CALLSIGN_LEN
        dest_callsign = 'DEST'
        dest_ssid = 1
        invalid_src_callsign = 'INVALID_CALLSIGN'
        src_ssid = 1
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid source callsign length
        with self.assertRaisesRegex(Ax25Error, 'src callsign must be less than 6 chars'):
            generate_ax25_packet(dest_callsign, dest_ssid, invalid_src_callsign, src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_src_ssid_larger(self):
        #Set source ssid to be greater than 15
        dest_callsign = 'DEST'
        dest_ssid = 1
        src_callsign = 'SRC'
        invalid_src_ssid = 16
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid invalid source ssid value
        with self.assertRaisesRegex(Ax25Error, 'src_ssid must be between 0 and 15'):
            generate_ax25_packet(dest_callsign, dest_ssid, src_callsign, invalid_src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_src_ssid_small(self):
        #Set source ssid with to be less than 0
        dest_callsign = 'DEST'
        dest_ssid = 1
        src_callsign = 'SRC'
        invalid_src_ssid = -1
        control = 1
        pid = 1
        payload = b'\x01\x02\x03'

        # Check if Ax25Error is raised for the invalid source ssid value
        with self.assertRaisesRegex(Ax25Error, 'src_ssid must be between 0 and 15'):
            generate_ax25_packet(dest_callsign, dest_ssid, src_callsign, invalid_src_ssid, control, pid, payload)

    def test_generate_ax25_invalid_payload(self):
        #Set payload with a length greater than AX25_PAYLOAD_MAX_LEN
        dest_callsign = 'DEST'
        dest_ssid = 1
        src_callsign = 'SRC'
        src_ssid = 1
        control = 1
        pid = 1
        invalid_payload = b'\x00' * (AX25_PAYLOAD_MAX_LEN + 1)

        # Check if Ax25Error is raised for the invalid source ssid value
        with self.assertRaisesRegex(Ax25Error, f'payload must be less than {AX25_PAYLOAD_MAX_LEN} bytes'):
            generate_ax25_packet(dest_callsign, dest_ssid, src_callsign, src_ssid, control, pid, invalid_payload)
