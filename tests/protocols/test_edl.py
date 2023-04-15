import unittest

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

        #Creating an instance of EdlServer with a dummy HMAC key and sequence number
        hmac_key = b'\x00' * 128
        seq_num = 0
        server = EdlServer(hmac_key, seq_num)

        #Preparing a packet that is shorter than the minimum length
        short_packet = b'\x00' * (server._TC_MIN_LEN - 1)

        #Test if EdlError "EDL packet too short" exception is thrown
        with self.assertRaisesRegex(EdlError, f'EDL packet too short: {server._TC_MIN_LEN - 1}'):
            server._parse_packet(short_packet, src_dest = 0) #Using 0 as a dummy src_dest value
