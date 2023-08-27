import unittest

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandResponse


class TestEdlCommandRequest(unittest.TestCase):

    def test_pack_unpack(self):

        req = EdlCommandRequest(EdlCommandCode.TX_CTRL, (True,))
        raw = req.pack()
        req2 = EdlCommandRequest.unpack(raw)
        self.assertEqual(req, req2)


class TestEdlCommandResponse(unittest.TestCase):

    def test_pack_unpack(self):

        res = EdlCommandResponse(EdlCommandCode.TX_CTRL, (True,))
        raw = res.pack()
        res2 = EdlCommandResponse.unpack(raw)
        self.assertEqual(res, res2)
