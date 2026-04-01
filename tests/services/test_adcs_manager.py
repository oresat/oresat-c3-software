import unittest

from canopen.objectdictionary import ODRecord
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

    def test_magnetometer_data(self):
        import numpy as np
        adcs_record: ODRecord = self.node.od["adcs"]
        values = np.array([1, 2, 3])
        # write known inputs to OD
        for direction in ("pos", "min"):
            for num in range(1, 3):
                i: int = 0
                for dim in ("x", "y", "z"):
                    adcs_record[f"{direction}_z_magnetometer_{num}_{dim}"].value = values[i]
                    i = (i + 1) % 3
        self.node.od["adcs"].value = adcs_record
        b = self.service.get_magnetometer_data()
        compare = values * 1e-7 # conver to Tesla
        self.assertTrue((b == compare).all())