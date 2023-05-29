import unittest

from spacepackets.uslp.frame import TransferFrame, FrameType
from oresat_c3.protocols.edl import EdlServer, EdlClient, EdlError


class TestEdl(unittest.TestCase):

    def test_telecommand(self):

        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        req_packet = client.generate_request(payload)
        req_playout = server.parse_request(req_packet)
        self.assertEqual(payload, req_playout)

        res_packet = server.generate_response(payload)
        res_playout = client.parse_response(res_packet)
        self.assertEqual(payload, res_playout)

    def test_parse_packet_short_packet(self):

        # Creating an instance of EdlServer with a dummy HMAC key and sequence number
        hmac_key = b'\x00' * 128
        seq_num = 0
        server = EdlServer(hmac_key, seq_num)

        # Preparing a packet that is shorter than the minimum length
        short_packet = b'\x00' * (server._TC_MIN_LEN - 1)

        # Test if EdlError "EDL packet too short" exception is thrown
        with self.assertRaises(EdlError):
            server.parse_request(short_packet)

    def test_parse_packet_invalid_fecf(self):

        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        # Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        # Generating a valid request ticket
        req_packet = client.generate_request(payload)

        # Modifying FECF so that it is Invalid
        invalid_fecf_packet = req_packet[:-2] + b'\xFF\xFF'

        # Checking if EdlError exception is raised for the invalid FECF
        with self.assertRaises(EdlError):
            server.parse_request(invalid_fecf_packet)

    def test_parse_packet_invalid_packet_or_frame_len(self):
        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        # Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        # Generating a valid request packet
        req_packet = client.generate_request(payload)

        # Modifying the packet length in the primary header so that it's invalid
        invalid_packet_len = 255
        invalid_packet = req_packet[:4] + invalid_packet_len.to_bytes(2, 'big') + req_packet[6:]

        with self.assertRaises(EdlError):
            server.parse_request(invalid_packet)

    def test_parse_packet_invalid_sequence_number(self):
        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        # Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        # Generating a valid request packet
        req_packet = client.generate_request(payload)

        # Create a frame with an invalid insert_zone value
        frame = TransferFrame.unpack(req_packet, FrameType.VARIABLE, server.FRAME_PROPS)
        frame.insert_zone = server.sequence_number_bytes + bytes(1)
        invalid_packet = frame.pack(frame_type=FrameType.VARIABLE)

        # Checking if the EdlError is raised for invalid sequence number
        with self.assertRaises(EdlError):
            server.parse_request(invalid_packet)

    def test_parse_packet_invalid_HMAC(self):
        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        # Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        # Generating a valid request packet
        req_packet = client.generate_request(payload)

        # Create a frame with a valid insert_zone value and an invalid HMAC
        frame = TransferFrame.unpack(req_packet, FrameType.VARIABLE, server.FRAME_PROPS)
        frame.insert_zone = server.sequence_number_bytes
        frame.tfdf.tfdz = payload + b'\x00' * server.HMAC_LEN
        invalid_packet = frame.pack(frame_type=FrameType.VARIABLE)

        with self.assertRaises(EdlError):
            server.parse_request(invalid_packet)
