import unittest
from unittest.mock import patch
from oresat_c3.protocols.edl import EdlServer, EdlClient, EdlError, crc16_bytes
from spacepackets.uslp.frame import TransferFrame, FrameType

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

    def test_parse_packet_invalid_fecf(self):

       hmac_key = b'\x00' * 128
       seq_num = 0
       payload = b'\x12\x34\x56'

       #Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
       server = EdlServer(hmac_key, seq_num)
       client = EdlClient(hmac_key, seq_num)

       #Generating a valid request ticket
       req_packet = client.generate_request(payload)

       #Modifying FECF so that it is Invalid
       invalid_fecf_packet = req_packet[:-2] + b'\xFF\XFF'

       #Checking if EdlError exception is raised for the invalid FECF
       crc16_raw = invalid_fecf_packet[-2:]
       crc16_raw_calc = crc16_bytes(invalid_fecf_packet[:-2])
       with self.assertRaisesRegex(EdlError, f'invalid FECF: .* vs .*'):
        server._parse_packet(invalid_fecf_packet, src_dest = 0)

    def test_parse_packet_invalid_packet_or_frame_len(self):
       hmac_key = b'\x00' * 128
       seq_num = 0
       payload = b'\x12\x34\x56'

       #Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
       server = EdlServer(hmac_key, seq_num)
       client = EdlClient(hmac_key, seq_num)

       #Generating a valid request packet
       req_packet = client.generate_request(payload)

       #Modifying the packet length in the primary header so that it's invalid
       invalid_packet_len = 255
       invalid_packet = req_packet[:4] + invalid_packet_len.to_bytes(2, 'big') + req_packet[6:]
       #mock_crc16_bytes.return_value = invalid_packet[-2:]

       #Checking if EdlError is raised for invalid packet or fram length
       #Use patch as a context manager
       with patch("oresat_c3.protocols.edl.crc16_bytes") as mock_crc16_bytes:
           mock_crc16_bytes.return_value = invalid_packet[-2:]
           with self.assertRaisesRegex(EdlError, 'USLP invalid packet or frame length'):
              server._parse_packet(invalid_packet, src_dest = 0)

    def test_parse_packet_invalid_sequence_number(self):
        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        #Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        #Generating a valid request packet
        req_packet = client.generate_request(payload)

        #Use patch as a context manager
        with patch("oresat_c3.protocols.edl.TransferFrame.unpack") as mock_unpack:
            #Create a mock frame with an invalid insert_zone value
            mock_frame = TransferFrame(req_packet, FrameType.VARIABLE)
            mock_frame.insert_zone = server.sequence_number_bytes + bytes(1)

            #Set the return value of the mocked unpack method
            mock_unpack.return_value = mock_frame

            #Checking if the EdlError is raised for invalid sequence number
            with self.assertRaisesRegex(EdlError, f'invalid sequence number: .* vs .*'):
                server._parse_packet(req_packet, src_dest=0)

    def test_parse_packet_invalid_HMAC(self):
        hmac_key = b'\x00' * 128
        seq_num = 0
        payload = b'\x12\x34\x56'

        #Creating an instance of EdlServer and EdlClient with a dummy HMAC key and sequence number
        server = EdlServer(hmac_key, seq_num)
        client = EdlClient(hmac_key, seq_num)

        #Generating a valid request packet
        req_packet = client.generate_request(payload)

        #Use patch as a context manager
        with patch("oresat_c3.protocols.edl.TransferFrame.unpack") as mock_unpack:
            #Create a mock frame with a valid insert_zone value and an invalid HMAC
            mock_frame = TransferFrame(req_packet, FrameType.VARIABLE)
            mock_frame.insert_zone = server.sequence_number_bytes
            mock_frame.tfdf.tfdz= payload + b'\x00' * server.HMAC_LEN

            #Set the return value of the mocked unpack method
            mock_unpack.return_value = mock_frame

            with self.assertRaisesRegex(EdlError,  f'invalid HMAC .* vs .*'):
                server._parse_packet(req_packet, src_dest=0)
