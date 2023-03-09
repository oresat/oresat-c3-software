import unittest

from oresat_c3.edl import EdlServer, EdlClient


class TestEdl(unittest.TestCase):

    def test_telecommand(self):

        hmac_key = b'\x00' * EdlServer._HMAC_KEY_LEN
        seq_num = 0
        payload = b'\x12\x34\x56'

        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        req_packet = client.generate_telecommand_request(payload)
        req_playout = server.parse_telecommand_request(req_packet)
        self.assertEqual(payload, req_playout)

        res_packet = server.generate_telecommand_response(payload)
        res_playout = client.parse_telecommand_response(res_packet)
        self.assertEqual(payload, res_playout)
