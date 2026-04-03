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
        adcs_config = build_config(str(config.mission))

        self.service = ADCSManager(adcs_config, mock_hw=True)

        self.node._setup_node()
        self.node._destroy_node()

        # initial the service, but stop the thread
        self.service._event.set()
        self.service.start(self.node)
        self.service.stop()

    def test_star_tracker_data(self):
        self.service._on_star_tracker_data("orientation_time_since_midnight", 111000111)
        self.assertEqual(self.service._sensor_data_buffer["star_tracker_1"].timestamp, 111000111)
        self.assertTrue(
            self.service._sensor_data_valid_buffer["star_tracker_1"][
                "orientation_time_since_midnight"
            ],
        )

        test_data = {
            "orientation_attitude_known": True,
            "orientation_attitude_i": 0.00786371,
            "orientation_attitude_j": 0.5304,
            "orientation_attitude_k": -0.0768838,
            "orientation_attitude_real": 0.844218,
        }

        for k, v in test_data.items():
            self.service._on_star_tracker_data(k, v)

        self.assertTrue("star_tracker_1" in self.service._sensor_data)
        self.assertFalse("star_tracker_1" in self.service._sensor_data_buffer)
        self.assertTrue(self.service._sensor_data["star_tracker_1"].data.attitude_known)

    def test_gps_data(self):
        self.service._on_gps_data("skytraq_time_since_midnight", 111000111)
        self.assertEqual(self.service._sensor_data_buffer["gps"].timestamp, 111000111)
        self.assertTrue(
            self.service._sensor_data_valid_buffer["gps"]["skytraq_time_since_midnight"],
        )

        test_data = {
            "skytraq_ecef_x": 1,
            "skytraq_ecef_y": 2,
            "skytraq_ecef_z": 3,
            "skytraq_ecef_vx": 4,
            "skytraq_ecef_vy": 5,
            "skytraq_ecef_vz": 6,
        }

        for k, v in test_data.items():
            self.service._on_gps_data(k, v)

        self.assertTrue("gps" in self.service._sensor_data)
        self.assertFalse("gps" in self.service._sensor_data_buffer)
        self.assertEqual(self.service._sensor_data["gps"].data.position[1], 2)

    def test_imu_data(self):
        self.service._on_imu_data("gyroscope_pitch_rate", 0.01)
        self.assertNotEqual(self.service._sensor_data_buffer["adcs"].timestamp, -1)
        self.assertTrue(
            self.service._sensor_data_valid_buffer["adcs"]["gyroscope_pitch_rate"],
        )

        test_data = {
            "gyroscope_yaw_rate": -0.03,
            "gyroscope_roll_rate": 0.02,
        }

        for k, v in test_data.items():
            self.service._on_imu_data(k, v)

        self.assertTrue("adcs" in self.service._sensor_data)
        self.assertFalse("adcs" in self.service._sensor_data_buffer)
        self.assertEqual(self.service._sensor_data["adcs"].data.gyro[1], -0.03)

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
        compare = values * 1e-7  # convert to Tesla
        self.assertTrue((b == compare).all())

    def test_get_sensor_data(self):
        self.service._sensor_data.clear()
        self.service._sensor_data_buffer.clear()
        self.test_star_tracker_data()
        data = self.service.get_sensor_data("star_tracker_1")
        self.assertIsNotNone(data)
        self.assertEqual(data.timestamp, self.service.last_sensor_time["star_tracker_1"])

    def test_is_data_available(self):
        self.service._sensor_data.clear()
        self.service._sensor_data_buffer.clear()
        self.assertFalse(self.service.is_data_available)
        self.test_star_tracker_data()
        self.assertFalse(self.service.is_data_available)
        self.test_gps_data()
        self.assertFalse(self.service.is_data_available)
        self.test_imu_data()
        self.assertTrue(self.service.is_data_available)
