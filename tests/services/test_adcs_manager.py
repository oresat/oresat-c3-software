import unittest

from olaf import CanNetwork, MasterNode
from oresat_configs import Mission, OreSatConfig

from oresat_c3.services.adcs_manager import ADCSManager
from oresat_c3.subsystems.adcs.config import build_config


class TestState(unittest.TestCase):
    """Test the C3 state service."""

    def setUp(self):
        config = OreSatConfig(Mission.default())
        self.od = config.od_db["c3"]
        network = CanNetwork("virtual", "vcan0")
        self.node = MasterNode(network, self.od, config.od_db)
        adcs_config = build_config()

        self.service = ADCSManager(adcs_config, mock_hw=True)

        self.node._setup_node()
        self.node._destroy_node()

        # initial the service, but stop the thread
        self.service._event.set()
        self.service.start(self.node)
        self.service.stop()

    def test_star_tracker_data(self):
        self.service._on_star_tracker_data(
            "orientation_time_since_midnight",
            111000111
        )
        self.assertEqual(
            self.service._sensor_data_buffer["star_tracker_1"].timestamp,
            111000111
        )
        self.assertTrue(
            self.service._sensor_data_valid_buffer["star_tracker_1"]["orientation_time_since_midnight"],
            True
        )