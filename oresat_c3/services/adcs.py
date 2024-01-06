"""ADCS Service"""

import math
import json
import threading
from time import time, sleep, monotonic_ns

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId


"""
For node, index, and subindex references, see oresat configs base
"""

class AdcsService(Service):
    """ADCS Service"""


    def __init__(self, config: dict):
        super().__init__()
        self.xyz_sensor_names = ['accelerometer',
                                   'gyroscope',
                                   'pos_z_magnetometer_1',
                                   'pos_z_magnetometer_2',
                                   'min_z_magnetometer_1',
                                   'min_z_magnetometer_2']
        self.actuator_names = ['mt_x', 'mt_y', 'mt_z', 'rw_1', 'rw_2', 'rw_3', 'rw_4']
        
        self.sensor_data = dict()
        for sensor in self.xyz_sensor_names:
            self.sensor_data[sensor] = dict()
        
        self.control_signals = dict()
        self.actuator_feedback = dict()
        for actuator in self.actuator_names:
            self.sensor_data[actuator] = dict()
            self.control_signals[actuator] = 0.0
            self.actuator_feedback[actuator] = 1.5

        logger.info("ADCS service object initiated")

    def on_start(self):
        logger.info("Starting ADCS")

        # Calibrate sensors and actuators
        self.gyro_calibrate()
        self.mag_calibrate()
        #self.rw_calibrate()

        # for ADCS testing
        #self.node.add_sdo_callbacks("adcs_manager", "reserved_rw", self.test_sdo_read, self.test_sdo_write)
        self.node.add_sdo_callbacks("adcs_manager", "feedback", self.mngr_feedback, None)
        self.node.add_sdo_callbacks("adcs_manager", "signals", None, self.mngr_signals_w)

        # ADCS startup complete
        logger.info("Completed ADCS startup")

    
    def on_loop(self):

        #logger.info("Starting iteration of ADCS loop")
        logger.info("START OF ADCS LOOP")

        # Read sensors, data is stored in self.sensor_data
        self.gyro_monitor()
        self.mag_monitor()
        self.gps_monitor()
        self.gps_time()
        ecef_data = self.gps_ecef_monitor()

        # Read actuators
        self.mt_monitor()
        #self.rw_monitor()

        # More things to read
        star_orientation = self.star_monitor()
        solar_power = self.solar_monitor()
        temperatures = self.temperature_monitor()
        batteries = self.battery_monitor()


        # Send control signal
        # Control signals turned off for sensor testing, for now
        self.mt_control()
        #self.rw_control()        


        # End of ADCS control loop
        sleep(1)

    def test_sdo_read(self, *args):
        logger.info("SDO read called!")
        logger.info(args)
        return 222

    def test_sdo_write(self, *args):
        logger.info("SDO write called!")
        logger.info(args)

    
    def mngr_signals_w(self, controls):
        """Apply control signals from ADCS manager SDO callback"""
        logger.info("write")
        logger.info(controls)

    def mngr_feedback(self):
        logger.info(self.actuator_feedback)
        return json.dumps(self.actuator_feedback)


    # gyro Functions
    def gyro_calibrate(self):
        #logger.info("Calibrating gyroscopes")
        pass

    def gyro_monitor(self):
        """Monitors the gyroscope"""
        logger.debug("Monitoring gyroscope")
        # pitch roll and yaw should be relative to velocity, convert back to xyz
        directions = {"pitch_rate": "x","roll_rate": "y","yaw_rate":"z"}
        for name,axis in directions.items():
            self.sensor_data["gyroscope"][axis] = self.node.od["adcs"]["gyroscope_" + name].value

    def gps_monitor(self, log_it=False):
        """Monitors the GPS readings"""
        #logger.debug("Monitoring GPS")
        if log_it:
            for name, item in self.node.od["gps"].items():
                logger.info(f"Key: {name} Value: {item.value}")

    def gps_time(self):
        """Gets the gps time since midnight"""
        logger.info("GPS time: %s"%self.node.od["gps"]["skytraq_time_since_midnight"].value)

    def gps_ecef_monitor(self):
        axis_list = ["x", "y", "z"]
        ecef_data = dict()
        ecef_data["position"] = {axis: self.node.od["gps"]["skytraq_ecef_" + axis].value for axis in axis_list}
        ecef_data["velocity"] = {axis: self.node.od["gps"]["skytraq_ecef_v" + axis].value for axis in axis_list}
        
        return ecef_data




    # MAG Functions
    def mag_calibrate(self):
        """Calibrates the magnetometers"""
        #logger.info("Calibrating Magnetometers")
        pass

    def mag_monitor(self):
        """Monitors the magnetometer readings"""
        logger.debug("Monitoring magnetometers")
        # full names are a little long, shorten them for now
        mag_map = {'pos_z_magnetometer_1': 'mag_pz1',
                   'pos_z_magnetometer_2': 'mag_pz2',
                   'min_z_magnetometer_1': 'mag_nz1',
                   'min_z_magnetometer_2': 'mag_nz2',
                   }
        directions = ["x", "y", "z"]
        for name,nick in mag_map.items():
            self.sensor_data[nick] = dict()
            for axis in directions:
                self.sensor_data[nick][axis] = self.node.od["adcs"][name + "_" + axis].value



    # Magnetorquer Functions
    def mt_calibrate(self):
        """Calibrate magnetorquers"""
        #logger.info("Calibrating magnetorquers")
        pass

    def mt_monitor(self):
        """Monitor magnetorquers"""
        logger.info("Monitoring magnetorquers")
        directions = {"current_x": "x", "current_y": "y", "current_z": "z"}
        self.sensor_data["magnetorquer"] = dict()
        for name,axis in directions.items():
            self.sensor_data["magnetorquer"][axis] = self.node.od["adcs"]["magnetorquer_" +name].value

    def mt_control(self, name=None, signal=0):
        """Send control signal to magnetorquers"""
        logger.info("Sending control signal to magnetorquers")
        if name is None:
            return
        self.write_sdo('adcs', 'magnetorquer', name, signal)

    
    # Reaction wheel functions
    def rw_apply_state(self, rw_name, state):
        self.write_sdo(rw_name, 'requested', 'state', 1)
        self.write_sdo(rw_name, 'requested', 'state', state)

    def rw_calibrate(self):
        #logger.info("Calibrating reaction wheels")
        
        def calibrate(rw_name, calibration_state):
            self.rw_apply_state(rw_name, calibration_state)
            for i in range(3):
                logger.info(rw_state:=self.node.od[rw_name]["ctrl_stat_current_state"].value)
                if rw_state == 3:
                    while True:
                        logger.info(f"SYSTEMD ERROR FOR {rw_name}, REBOOT!")
                if rw_state == 4:
                    logger.info(f"CONTROLLER ERROR FOR {rw_name}, ATTEMPTING TO CLEAR ERRORS")
                    self.rw_apply_state(rw_name, 13)
                    self.rw_apply_state(rw_name, calibration_state)

                sleep(1)

        # Calibrate
        #calibrate("rw_1", 7)
        #calibrate("rw_1", 8)
        #calibrate("rw_1", 9)
        #calibrate("rw_1", 10)
        # set velocity control
        #self.rw_apply_state("rw_1", 5)

        pass

    def rw_monitor(self, num_rws=4, log_it=False):
        """Retreives reaction wheel states"""
        endpoints = ['motor_velocity', 'motor_current', 'bus_current', 'bus_voltage']
        for num in range(1, num_rws+1):
            self.sensor_data['rw_'+str(num)] = {endpoint: self.node.od['rw_'+str(num)][endpoint].value for endpoint in endpoints}
            self.actuator_feedback['rw_'+str(num)] = self.node.od['rw_'+str(num)]['motor_velocity'].value

        if log_it:
            for num in range(1, num_rws+1):
                logger.info("RW %s state: %s"%(num, self.sensor_data['rw_'+str(num)]))
        

    def rw_control(self):
        """Sends the control signal to the reaction wheels"""
        
        logger.info("Sending control signal to reaction wheels")
        # request velocity control (6???)
        self.write_sdo('rw_1', 'requested', 'state', 5)
        pass





    # Other attitude determination functions
    def solar_monitor(self, num_modules=6):
        """Returns a dictionary of solar power generation data

        Parameters:
            num = the number of modules (modules are named 'solar_num')
        """
        logger.debug("Monitoring solar modules")
        return {module: self.node.od[module]["output_power"].value 
                for module in ["solar_"+str(num) for num in range(1, num_modules+1)]}

    def star_monitor(self, num_modules=1):
        """Returns a dictionary of star tracker orientation data

        Parameters:
            num = the number of modules (modules are named 'star_tracker_num' starting with 1)
        """
        logger.debug("Monitoring star tracker")
        # Note there are two star trackers
        return {"star_tracker_" + str(tracker_num): 
                {subindex: self.node.od["star_tracker_"+str(tracker_num)][str("orientation_" + subindex)].value
                for subindex in ["right_ascension", "declination", "roll", "time_since_midnight"]}
                for tracker_num in range(1, num_modules+1)}


    # Additional data retrieval to consider control type
    def temperature_monitor(self, num_solar_modules=6):
        """Records the temperatures from the imu and solar modules"""
        logger.debug("Monitoring temperature sensors")
        # Note that modules have a cell 1 and cell 2
        temps = {module: self.node.od[module]["cell_1_temperature"].value
                 for module in ["solar_"+str(num) for num in range(1, num_solar_modules+1)]}
        temps["adcs"] = self.node.od["adcs"]["temperature"].value
        return temps

    def battery_monitor(self, num_cards=1, num_packs=2):
        """Returns a dictionary of battery information"""
        logger.debug("Monitoring battery reported capacities")
        return {"battery_%s_pack_%s"%(battery, pack): 
                self.node.od["battery_%s"%battery]["pack_%s_reported_capacity"%pack].value
                for battery in range(1, num_cards+1)
                for pack in range(1, num_packs+1)}

    # HELPER FUNCTIONS
    def write_sdo(self, node, index, subindex, value):
        """Mock function 
        
        Paramters:
        node = the card to write to
        index = the index to write to
        subindex = the subindex to write to
        value = the value to send
        """

        try:
            self.node.sdo_write(node, index, subindex, value)
        except Exception as e:
            logger.warning(f"An error occured with sending SDO: {e}")
            logger.warning(f"node: {node}, index: {index}, subindex: {subindex}, value: {value}")

    def vect_normalize(self, vect: dict):
        """Returns the normalized vector"""
        magnitude = math.hypot(*vect.values())
        if magnitude == 0:
            # why z? because it is the easiest axis to rotate on
            return {"x": 0, "y": 0, "z": 1}
        norm_vect = dict()
        for key,val in vect.items():
            norm_vect[key] = val / magnitude
        return norm_vect

    def vect_dot_product(self, vect1: dict, vect2: dict):
        """Retuns the value of the dot product between two vectors"""
        return vect1["x"]*vect2["x"] + vect1["y"]*vect2["y"] + vect1["z"]*vect2["z"]

    def vect_cross_product(self, vect1: dict, vect2: dict):
        """Returns a dictionary of the cross product"""
        return {"x": vect1["y"]*vect2["z"] - vect1["z"]*vect2["y"],
                "y": vect1["z"]*vect2["x"] - vect1["x"]*vect2["z"],
                "z": vect1["x"]*vect2["y"] - vect1["y"]*vect2["x"]}

    def get_rot_vect(self, vect1: dict, vect2: dict):
        """Calculates the rotation vector based on two vectors

        Paramters:
        vect1 = dictionary of first vector
        vect2 = dictionary of second vector

        Returns: angle = rotation in radians, vector = normalized vector of rotation"""

        # First, the direction of rotation is the normalized cross product
        vect = self.vect_normalize(self.vect_cross_product(vect1, vect2))
        # Next, find the angle of rotation, use the dot product instead
        angle = math.acos(self.vect_dot_product(vect1,vect2) 
                                  / (math.hypot(*vect1.values())*math.hypot(*vect2.values())))

        return angle, vect

    def rot_vect_to_quat(self, angle: float, vect: dict):
        """Converts rotation vector to quaternion

        Parameters:
        angle = angle in radians
        vect = dictionary of normalized vector {x, y, z}
        
        Return: quaternion = dictionary of normalized quaternion {h, i, j, k}"""

        #logger.debug(f"Converting angle {angle} and vector {vect} into a rotation quaternion")

        #if (vdiff:=abs(math.hypot(*vect.values()) - 1)) > 0.00000001:
        #    logger.warning("WARNING: vector for vector to quaternion conversion is not a unit vector")
        #    logger.warning(f"unit vector diff: {vdiff}")

        quat = {"h": math.cos(angle/2) , 
                "i": math.sin(angle/2)*vect["x"], 
                "j": math.sin(angle/2)*vect["y"], 
                "k": math.sin(angle/2)*vect["z"]}

        #if (qdiff:=abs(math.hypot(*quat.values()) - 1)) > 0.00000001:
        #    logger.warning("WARNING: quaternion conversion did not result in unit quaternion")
        #    logger.warning(f"unit quaternion diff: {qdiff}")
        return quat

    def quat_product(self, quat1, quat2):
        """Calculates the product of two quaternions"""
        # define vectors as quat{i, j, k} -> vect{x, y, z}}
        # Warning! qvect_cross is in the form {x, y, z}
        qvect_cross = self.vect_cross_product(qvect1:={"x": quat1["i"], "y": quat1["j"], "z": quat1["k"]},
                                              qvect2:={"x": quat2["i"], "y": quat2["j"], "z": quat2["k"]})

        # qp = (q.h)(p.h) - dot(q.v,p.v) + (q.h)(p.v) + (p.h)(q.v) + cross(q.v,p.v)
        result_quat = {"h": quat1["h"]*quat2["h"] - self.vect_dot_product(qvect1, qvect2),
                       "i": quat1["h"]*quat2["i"] + quat2["h"]*quat1["i"] + qvect_cross["x"],
                       "j": quat1["h"]*quat2["j"] + quat2["h"]*quat1["j"] + qvect_cross["y"],
                       "k": quat1["h"]*quat2["k"] + quat2["h"]*quat1["k"] + qvect_cross["z"]}

        return result_quat
