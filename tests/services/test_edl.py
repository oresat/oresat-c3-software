"""
Class to test that the edl service is handling commands correctly

Creats a lot of mock classes that report values so that we know that, as well as parsing and
returning correctly, the commands have the desired result.
"""

import unittest
from queue import SimpleQueue
from time import sleep, time
from typing import NamedTuple, Optional

from canopen.sdo.exceptions import SdoAbortedError
from olaf import CanNetwork, MasterNode, NodeStop
from oresat_configs import Mission, OreSatConfig
from spacepackets.uslp import TransferFrame

from oresat_c3.protocols.edl_command import EdlCommandCode, EdlCommandRequest, EdlCommandResponse
from oresat_c3.protocols.edl_packet import EdlPacket, EdlVcid
from oresat_c3.protocols.uslp import make_frame, unpack_frame
from oresat_c3.services.beacon import BeaconService
from oresat_c3.services.channel_router import ChannelRouterService
from oresat_c3.services.edl import EdlService
from oresat_c3.services.node_flasher import NodeFlasherService
from oresat_c3.services.node_manager import NodeManagerService
from oresat_c3.subsystems.opd import OpdNodeState, OpdState

HMAC = bytes(32)

class NodeHeartbeatInfo(NamedTuple):
    state: int
    timestamp: float
    time_since_boot: float

def make_cmd(cmd: EdlCommandCode, values: tuple | None, q: SimpleQueue) -> TransferFrame:
    payload = EdlCommandRequest(cmd, values).pack()
    frame = make_frame(payload, 0, 1, hmac_key=HMAC)
    q.put(frame)

def to_response(resp_raw: bytes) -> EdlCommandResponse:
    return EdlPacket.from_frame(unpack_frame(resp_raw), HMAC).payload

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
        make_cmd(EdlCommandCode.TX_CTRL, (True,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.TX_CTRL)
        self.assertEqual(response.values[0], (True))
        self.assertEqual(tx_enable.value, True)
        self.assertTrue(start_time >= last_enable.value)

        # disable
        make_cmd(EdlCommandCode.TX_CTRL, (False,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.TX_CTRL)
        self.assertEqual(response.values[0], (False))
        self.assertEqual(tx_enable.value, False)
        self.assertEqual(last_enable.value, 0)

    def test_soft_reset(self):
        """1: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        make_cmd(EdlCommandCode.C3_SOFT_RESET, (), self.mock_router.uplink_edl)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.SOFT_RESET)

    def test_hard_reset(self):
        """2: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        make_cmd(EdlCommandCode.C3_HARD_RESET, (), self.mock_router.uplink_edl)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.HARD_RESET)

    def test_factory_reset(self):
        """3: No inputs. Should edit self.node.value_set_by_edl. Should not reply."""
        self.node.value_set_by_edl = NodeStop.NO_STOP

        make_cmd(EdlCommandCode.C3_FACTORY_RESET, (), self.mock_router.uplink_edl)
        sleep(0.1)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        self.assertEqual(self.node.value_set_by_edl, NodeStop.FACTORY_RESET)

    def test_co_node_enable_reset(self):
        """4: Vestigal and no longer used."""
        pass

    def test_co_node_status(self):
        """5: 1 input. returns the heartbeat status of the relevant node."""
        self.node.node_status["star_tracker_1"] = NodeHeartbeatInfo(0x05, 0,0)

        make_cmd(EdlCommandCode.CO_NODE_STATUS, (0x2C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.CO_NODE_STATUS)
        self.assertEqual(response.values[0], 0x05)

    def test_co_sdo_write_local(self):
        """6: 5 inputs. expect a uint32 back with the error code, 0 if none. Tests writing to c3."""
        od_val = self.node.od["reset_timeout"]
        od_val.value = 10000

        make_cmd(
            EdlCommandCode.CO_SDO_WRITE,
            (0x1,0x4001,0x0,0x4,(20000).to_bytes(4, "little")),
            self.mock_router.uplink_edl
        )
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.CO_SDO_WRITE)
        self.assertEqual(response.values[0], (0x0))
        self.assertEqual(int(od_val.value), 20000)

    def test_co_sdo_write_remote(self):
        """
        6: 5 inputs. expect a uint32 back with the error code, 0 if none. Tests "writing" to star
        tracker. Does not actually write, just sets value_set_by_edl = True
        """
        self.node.should_fail_test = False
        self.node.value_set_by_edl = False

        make_cmd(
            EdlCommandCode.CO_SDO_WRITE,
            (0x2C,0x4000,0x0,0x1,(2).to_bytes(1, "little")),
            self.mock_router.uplink_edl
        )
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.CO_SDO_WRITE)
        self.assertEqual(response.values[0], (0x0))
        self.assertEqual(self.node.value_set_by_edl, True)

    def test_co_sdo_write_fail(self):
        """
        6: 5 inputs. expect a uint32 back with the error code, 0 if none. This should fail and
        return nonzero error code.
        """
        self.node.should_fail_test = True
        self.node.value_set_by_edl = False

        make_cmd(
            EdlCommandCode.CO_SDO_WRITE,
            (0x2C,0x4000,0x0,0x1,(2).to_bytes(4, "little")),
            self.mock_router.uplink_edl
        )
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.CO_SDO_WRITE)
        self.assertEqual(response.values[0], (0x05040000))
        self.assertEqual(self.node.value_set_by_edl, True)

    def test_co_sync(self):
        """7: sends a CO sync message. """
        self.node.value_set_by_edl = False

        make_cmd(EdlCommandCode.CO_SYNC,(),self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.CO_SYNC)
        self.assertEqual(response.values[0], True)
        self.assertEqual(self.node.value_set_by_edl, True)

    def test_opd_sysenable(self):
        """8: 1 input. Enables or disables the OPD."""
        self.mock_node_mgr.opd.enabled = False

        # enable
        make_cmd(EdlCommandCode.OPD_SYSENABLE, (True,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_SYSENABLE)
        self.assertEqual(response.values[0], (0x1))
        self.assertEqual(self.mock_node_mgr.opd.enabled, True)

        # disable
        make_cmd(EdlCommandCode.OPD_SYSENABLE, (False,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_SYSENABLE)
        self.assertEqual(response.values[0], (0x0))
        self.assertEqual(self.mock_node_mgr.opd.enabled, False)

    def test_opd_scan(self):
        """9. No inputs. Should return 2 in this test setup."""
        make_cmd(EdlCommandCode.OPD_SCAN, None, self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_SCAN)
        self.assertEqual(response.values[0], 2)

    def test_opd_probe(self):
        """10. 1 input. returns if the node was found."""
        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.DISABLED

        # found
        make_cmd(EdlCommandCode.OPD_PROBE, (0x1C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_PROBE)
        self.assertEqual(response.values[0], True)

        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.NOT_FOUND

        # not found
        make_cmd(EdlCommandCode.OPD_PROBE, (0x1C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_PROBE)
        self.assertEqual(response.values[0], False)

    def test_opd_node_enable(self):
        """11: Takes 2 values, nodeid and value. Sends two commands to test both states."""
        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.DISABLED

        # enable
        make_cmd(EdlCommandCode.OPD_ENABLE, (0x1C, True), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_ENABLE)
        self.assertEqual(response.values[0], (0x1))
        self.assertEqual(self.mock_node_mgr.opd["star_tracker_1"].status, OpdNodeState.ENABLED)

        # disable
        make_cmd(EdlCommandCode.OPD_ENABLE, (0x1C, False), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_ENABLE)
        self.assertEqual(response.values[0], (0x0))
        self.assertEqual(self.mock_node_mgr.opd["star_tracker_1"].status, OpdNodeState.DISABLED)

    def test_opd_reset(self):
        """12. 1 input. returns if the node state value."""
        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.DISABLED
        self.mock_node_mgr.opd["star_tracker_1"].was_reset = False

        # found
        make_cmd(EdlCommandCode.OPD_RESET, (0x1C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_RESET)
        self.assertEqual(response.values[0], 0x1)
        self.assertEqual(self.mock_node_mgr.opd["star_tracker_1"].was_reset, True)

    def test_opd_status(self):
        """13. 1 input. returns if the node state value."""
        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.ENABLED

        # enabled
        make_cmd(EdlCommandCode.OPD_STATUS, (0x1C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_STATUS)
        self.assertEqual(response.values[0], 0x1)

        self.mock_node_mgr.opd["star_tracker_1"].status = OpdNodeState.DISABLED

        # disabled
        make_cmd(EdlCommandCode.OPD_STATUS, (0x1C,), self.mock_router.uplink_edl)
        resp_raw = self.mock_router.downlink_edl.get(timeout=1.0)
        self.assertTrue(self.mock_router.downlink_edl.empty())
        response = to_response(resp_raw)
        self.assertEqual(response.code, EdlCommandCode.OPD_STATUS)
        self.assertEqual(response.values[0], 0x0)


class MockMasterNode(MasterNode):
    """MasterNode wrapper with overwritten functions that let us ensure that they are called."""
    def __init__(
        self,
        network,
        od,
        od_db,
    ) -> None:
        super().__init__(network, od, od_db)
        self.should_fail_test = False

    def stop(self, reset: NodeStop | None = None):
        self.value_set_by_edl = reset

    def sdo_write(
        self,
        key: str,
        index: int | str,
        subindex: int | str | None,
        value: str | float | bytes | bool,
    ) -> None:
        self.value_set_by_edl = True
        if self.should_fail_test:
            raise SdoAbortedError(0x05040000)

    def send_sync(self):
        self.value_set_by_edl = True


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
                """intent is that status is manually set prior to CMD."""
                return self.status != OpdNodeState.NOT_FOUND

            def reset(self) -> OpdNodeState:
                self.status = OpdNodeState.ENABLED
                self.was_reset = True
                return self.status


class MockOpd():
        def __init__(self):
            self.enabled = False
            self._nodes: dict[str, MockNode] = {}
            self._nodes["star_tracker_1"] = MockNode()
            self.status = OpdState.ENABLED

        def __getitem__(self, name: str) -> MockNode:
            return self._nodes[name]

        def enable(self):
            self.enabled = True
            self.status = OpdState.ENABLED

        def disable(self):
            self.enabled = False
            self.status = OpdState.DISABLED

        def scan(self) -> int:
            return 2


class MockNodeManagerService(NodeManagerService):
    """
    Cut down node manager that keeps track of last command. Will only contain information for star
    tracker 1 (arbitrary), and so if further tests are desired this should be changed.
    """
    def __init__(self):
        self.set_node = 0x0
        self.set_state = 0x0
        self.opd_addr_to_name = {0x0: "c3", 0x1C: "star_tracker_1"}
        self.node_id_to_name = {0x1: "c3", 0x2C: "star_tracker_1"}
        self.opd = MockOpd()

    def __del__(self):
        pass

