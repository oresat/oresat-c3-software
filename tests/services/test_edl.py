"""
Class to test that the edl service is handling commands correctly

Creats a lot of mock classes that report values so that we know that, as well as parsing and
returning correctly, the commands have the desired result.
"""

import unittest
from queue import SimpleQueue
from time import sleep, time
from typing import Optional

from olaf import CanNetwork, MasterNode, NodeStop
from oresat_configs import Mission, OreSatConfig
from spacepackets.uslp import TransferFrame

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest
from oresat_c3.protocols.edl_packet import EdlPacket, EdlVcid
from oresat_c3.protocols.uslp import make_frame, unpack_frame
from oresat_c3.services.beacon import BeaconService
from oresat_c3.services.channel_router import ChannelRouterService
from oresat_c3.services.edl import EdlService
from oresat_c3.services.node_flasher import NodeFlasherService
from oresat_c3.services.node_manager import NodeManagerService
from oresat_c3.subsystems.opd import OpdNodeState

HMAC = bytes(32)

def make_packet_frame(cmd: EdlCommandCode, values: tuple | None) -> TransferFrame:
    payload = EdlCommandRequest(cmd, values).pack()
    return make_frame(payload, 0, 1, hmac_key=HMAC)

class TestEdl(unittest.TestCase):
    """Test the C3 state service."""

    def setUp(self):
        config = OreSatConfig(Mission.default())
        self.od = config.od_db["c3"]
        network = CanNetwork("virtual", "vcan0")
        self.node = MockMasterNode(network, self.od, config.od_db)

        self.mock_node_mgr = MockNodeManagerService()
        self.beacon = MockBeaconService()
        self.mock_router = MockChannelRouterService()
        self.mock_flasher = MockNodeFlasherService()

        self.service = EdlService(
            self.node, self.mock_node_mgr, self.beacon, self.mock_router, self.mock_flasher
        )

        self.node._setup_node()

        # initial the service, but stop the thread
        self.service.start(self.node)

    def tearDown(self):
        self.node._destroy_node()
        self.service._event.set()
        self.service.stop()

    def test_tx_ctrl(self):
        """0: Takes 1 value. Edits CO tx_enable to be INPUT, last_enable based on input"""
        tx_enable = self.node.od["tx_control"]["enable"]
        last_enable = self.node.od["tx_control"]["last_enable_timestamp"]
        tx_enable.value = False
        last_enable.value = 0
        start_time = int(time())

        # enable
        frame = make_packet_frame(EdlCommandCode.TX_CTRL, (True,))
        self.mock_router.uplink_edl.put(frame)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = EdlPacket.from_frame(unpack_frame(resp_raw), HMAC).payload
        self.assertEqual(response.code, EdlCommandCode.TX_CTRL)
        self.assertEqual(response.values[0], (True))
        self.assertEqual(tx_enable.value, True)
        self.assertTrue(start_time >= last_enable.value)

        # disable
        frame = make_packet_frame(EdlCommandCode.TX_CTRL, (False,))
        self.mock_router.uplink_edl.put(frame)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = EdlPacket.from_frame(unpack_frame(resp_raw), HMAC).payload
        self.assertEqual(response.code, EdlCommandCode.TX_CTRL)
        self.assertEqual(response.values[0], (False))
        self.assertEqual(tx_enable.value, False)
        self.assertEqual(last_enable.value, 0)

    def test_soft_reset(self):
        """1: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        frame = make_packet_frame(EdlCommandCode.C3_SOFT_RESET, ())
        self.mock_router.uplink_edl.put(frame)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.SOFT_RESET)

    def test_hard_reset(self):
        """2: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        frame = make_packet_frame(EdlCommandCode.C3_HARD_RESET, ())
        self.mock_router.uplink_edl.put(frame)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.HARD_RESET)

    def test_factory_reset(self):
        """3: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        frame = make_packet_frame(EdlCommandCode.C3_FACTORY_RESET, ())
        self.mock_router.uplink_edl.put(frame)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.FACTORY_RESET)

    def test_opd_node_enable(self):
        """11: Takes 2 values, nodeid and value. Sends two commands to test both states."""
        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.DISABLED

        # enable
        frame = make_packet_frame(EdlCommandCode.OPD_ENABLE, (0x1C, True))
        self.mock_router.uplink_edl.put(frame)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = EdlPacket.from_frame(unpack_frame(resp_raw), HMAC).payload
        self.assertEqual(response.code,EdlCommandCode.OPD_ENABLE)
        self.assertEqual(response.values[0],(0x1))
        self.assertEqual(self.mock_node_mgr.opd["star_tracker_1"].status, OpdNodeState.ENABLED)

        # disable
        frame = make_packet_frame(EdlCommandCode.OPD_ENABLE, (0x1C, False))
        self.mock_router.uplink_edl.put(frame)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = EdlPacket.from_frame(unpack_frame(resp_raw), HMAC).payload
        self.assertEqual(response.code,EdlCommandCode.OPD_ENABLE)
        self.assertEqual(response.values[0],(0x0))
        self.assertEqual(self.mock_node_mgr.opd["star_tracker_1"].status, OpdNodeState.DISABLED)


class MockMasterNode(MasterNode):
    """MasterNode wrapper with an overwritten stop function. No type definitions to limit imports"""
    def __init__(
        self,
        network,
        od,
        od_db,
    ) -> None:
        super().__init__(network, od, od_db)

    def stop(self, reset: NodeStop | None = None):
        self.value_set_by_edl = reset


class MockNodeFlasherService(NodeFlasherService):
    """Cut down node flasher service to test if commands have the desired effect"""
    def __init__(self):
        self.told_to_flash = False

    def __del__(self):
        pass

    def enqueue_flash(
        self,
        node_id: int,
        filename: str,
        throttle_delay: Optional[float] = None,
        block_transfer: Optional[bool] = None,
        request_crc: Optional[bool] = None,
        confirm_image: Optional[bool] = None,
    ):
        # should this try to keep track of what node was flashed?
        self.told_to_flash = True


class MockChannelRouterService(ChannelRouterService):
    """Cut down channel router with queues to make sure responses are correct."""
    def __init__(self):
        self.uplink_edl = SimpleQueue()
        self.uplink_cfdp = SimpleQueue()
        self.downlink_edl = SimpleQueue()
        self.downlink_cfdp = SimpleQueue()

    def __del__(self):
        pass

    def request_downlink_route(self, vcid: EdlVcid) -> SimpleQueue[bytes]:
        if vcid == 0:
            return self.downlink_edl
        elif vcid == 1:
            return self.downlink_cfdp

    def request_uplink_route(
        self, vcid: EdlVcid, use_cop: bool = False
    ) -> SimpleQueue[TransferFrame]:
        if vcid == 0:
            return self.uplink_edl
        elif vcid == 1:
            return self.uplink_cfdp


class MockBeaconService(BeaconService):
    def __init__(self):
        self.told_to_beacon = False

    def __del__(self):
        pass

    def send(self):
        self.told_to_beacon = True


class MockNode():
            def __init__(self) -> None:
                self.status = OpdNodeState.NOT_FOUND

            def enable(self) -> OpdNodeState:
                self.status = OpdNodeState.ENABLED
                return self.status

            def disable(self) -> OpdNodeState:
                self.status = OpdNodeState.DISABLED
                return self.status

            def probe(self) -> bool:
                return self.status == OpdNodeState.NOT_FOUND

            def reset(self) -> OpdNodeState:
                self.status = OpdNodeState.ENABLED
                return self.status


class MockOpd():
        def __init__(self):
            self.enabled = False
            self._nodes: dict[str, MockNode] = {}
            self._nodes["star_tracker_1"] = MockNode()

        def __getitem__(self, name: str) -> MockNode:
            return self._nodes[name]

        def enable(self):
            self.enabled = True

        def disable(self):
            self.enabled = True

        def scan(self) -> int:
            return 1


class MockNodeManagerService(NodeManagerService):
    """
    Cut down node manager that keeps track of last command. Will only contain information for star
    tracker 1 (arbitrary), and so if further tests are desired this should be changed.
    """
    def __init__(self):
        self.set_node = 0x0
        self.set_state = 0x0
        self.opd_addr_to_name = {0x1C: "star_tracker_1"}
        self.node_id_to_name = {0x1C: "star_tracker_1"}
        self.opd = MockOpd()

    def __del__(self):
        pass

