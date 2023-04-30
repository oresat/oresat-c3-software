import unittest
from unittest import MagicMock, patch
from oresat_c3.resources.edl import EdlResource

class TestEdlResource(unittest. TestCase):

    @patch("socket.socket")
    @patch("edl_resource.EdlServer")
    def test_edl_thread_(self, mock_edl_server_class, mock_socket_class):
        #Mock instances for the dependencies
        mock_opd = MagicMock()
        mock_rtc = MagicMock()

        #Mock socket instances
        mock_uplink_socket = MagicMock()
        mock_downlink_socket = MagicMock()
        mock_ssocket_class.side_effect = [mock_uplink_socket, mock_downlink_socket]

        #Mock EdlServer instance
        mock_edl_server = MagicMock()
        mock_edl_server_class.return_value = mock_edl_server

        #Create an instance of EdlResource
        edl_resource = EdlResource(mock_opd, mock_rtc)

