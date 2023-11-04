"""Unit tests for EdlCommand classes."""

import unittest

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandResponse


class TestEdlCommandRequest(unittest.TestCase):
    """Test EdlCommandRequest class."""

    def test_pack_unpack(self):
        """Test pack and unpack method."""

        req = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        raw = req.pack()
        req2 = EdlCommandRequest.unpack(raw)
        self.assertEqual(req, req2)


class TestEdlCommandResponse(unittest.TestCase):
    """Test EdlCommandRequest class."""

    def test_pack_unpack(self):
        """Test pack and unpack method."""

        res = EdlCommandResponse(EdlCommandCode.TX_CTRL, (True,))
        raw = res.pack()
        res2 = EdlCommandResponse.unpack(raw)
        self.assertEqual(res, res2)
