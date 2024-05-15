"""ADCS Service"""

import math
import json
import threading
from time import time, sleep, monotonic_ns
from enum import Enum, IntEnum, unique

import canopen
from olaf import NodeStop, Service, logger
from oresat_configs import NodeId


@unique
class ADCS_Mode(IntEnum):
    NONE = 0
    STANDBY = 1         # STANDBY (everything is off)
    HOLD = 2            # Do not send SDOs, actuators may still be acting
    CALIBRATE = 3       # Temporary mission, remove
    SPINDOWN = 4        # Temporary mission
    DETUMBLE = 5        # Temporary mission
    BBQ = 6             # Continuous Mission
    POINT = 7           # Continuous Mission
    MANUAL = 8

@unique
class ADCS_Status(IntEnum):
    NONE = 0            # Nothing
    IDLE = 1            # Nothing, (probably) not sending SDOs
    STARTING = 2        # on_start() function
    MISSION = 3         # on_loop() function, All systems fine, running mission
    DEGRADED = 4        # Assuming some sensors or actators are not working but following mission
    UNSAFE = 5           # something went horribly wrong
    ERROR = 6          # Not safe to stop service, probably transistioning
    DONE = 7            # completed temporary 


@unique
class RW_State(IntEnum):
    NONE = 0
    IDLE = 1
    SYSTEM_ERROR = 2
    CONTROLLER_ERROR = 3
    TORQUE_CONTROL = 4
    VEL_CONTROL = 5
    POS_CONTROL = 6
    MOTOR_RESISTANCE_CAL = 7
    MOTOR_INDUCTANCE_CAL = 8
    ENCODER_DIR_CAL = 9
    ENCODER_OFFSET_CAL = 10
    ENCODER_TEST = 11
    OPEN_LOOP_CONTROL = 12
    CLEAR_ERRORS = 13


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
            self.actuator_feedback[actuator] = 0.0

        logger.info("ADCS service object initiated")
        self.calibrating = False
        self.status_code = ADCS_Status.NONE
        self.mode = ADCS_Mode.NONE

    def on_start(self):
        logger.info("Starting ADCS")

        self.set_status_code(ADCS_Status.STARTING)
        self.calibrating = False

        # Calibrate sensors and actuators
        #self.gyro_calibrate()
        #self.mag_calibrate()
        #self.rw_calibrate()

        # for ADCS testing
        #self.node.add_sdo_callbacks("adcs_manager", "reserved_rw", self.test_sdo_read, self.test_sdo_write)
        self.node.add_sdo_callbacks("adcs_manager", "mode", None, self.mngr_mode)
        self.node.add_sdo_callbacks("adcs_manager", "signals", None, self.mngr_signals)
        self.node.add_sdo_callbacks("adcs_manager", "feedback", self.mngr_feedback, None)

        # ADCS startup complete
        logger.info("Completed ADCS startup")
        self.set_status_code(ADCS_Status.MISSION)
    
    def on_loop(self):

        #logger.info("Starting iteration of ADCS loop")
        logger.info("START OF ADCS LOOP")

        if self.mode == ADCS_Mode.CALIBRATE:
            logger.info("Entering calibration state")
            sleep(2)
            # Check MT feedback
            # Calibrate RWs
            self.rw_calibrate()
            sleep(2)
            self.set_mode(ADCS_Mode.MANUAL)

        # Read sensors, data is stored in self.sensor_data
        self.gyro_monitor()
        self.mag_monitor(log=True)
        self.gps_monitor()
        self.gps_time()
        ecef_data = self.gps_ecef_monitor()

        # Read actuators
        self.mt_monitor()
        self.rw_monitor()

        # More things to read
        star_orientation = self.star_monitor()
        solar_power = self.solar_monitor()
        temperatures = self.temperature_monitor()
        batteries = self.battery_monitor()


        # Send control signal
        # Control signals turned off for sensor testing, for now
        self.mt_control(log=True)
        self.rw_control()        

        # End of ADCS control loop
        sleep(1)
    


    """
    HELPER FUNCTIONS
    """
    def write_sdo(self, node, index, subindex, value):
        """Wrapper function to handle sdo call functions while there are still many errors"""
        try:
            self.node.sdo_write(node, index, subindex, value)
        except Exception as e:
            logger.warning(f"An error occured with sending SDO: {e}")
            logger.warning(f"node: {node}, index: {index}, subindex: {subindex}, value: {value}")

    
    def set_status_code(self, status_code):
        """Set the status of the ADCS service"""
        logger.warning(f"Setting ADCS status to {status_code}")
        self.status_code = status_code
        # write the tpdo for it
    
    def set_mode(self, mode):
        """Set the mode of the ADCS service"""
        logger.warning(f"Setting ADCS mode to {mode}")
        self.mode = mode
        # write the tpdo for it


    def api(self, target_mode):
        logger.warning(f"Recieved request to got to mode {target_mode}")
        self.set_mode(target_mode)
        return 0

    """
    SDO CALLBACK FUNCTIONS
    """
    def mngr_mode(self, mode):
        """Retreive the requested ADCS mode"""
        self.set_mode(mode)
        pass

    def mngr_signals(self, controls):
        """Apply control signals from ADCS manager SDO callback"""
        # Only accept signals if the mission mode is manual
        if self.mode== ADCS_Mode.MANUAL:
            self.control_signals = json.loads(controls)
            logger.debug(self.control_signals)

    def mngr_feedback(self):
        """Return string of feedback signals for ADCS manager SDO callback"""
        # Always send feedback just in case
        logger.debug(self.actuator_feedback)
        return json.dumps(self.actuator_feedback)
    

    """
    PRIMARY SENSOR FUNCTIONS
    """
    # MAGNETOMETER FUNCTIONS
    def mag_calibrate(self):
        """Calibrates the magnetometers"""
        #logger.info("Calibrating Magnetometers")
        pass

    def mag_monitor(self, log=False):
        """Monitors the magnetometer readings"""
        if log:
            logger.info("Monitoring magnetometers")
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
            if log:
                logger.info(f"{name}: {self.sensor_data[nick]}")

    # GYROSCOPE FUNCTIONS
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


    """
    ACTUATOR FUNCTIONS
    """
    # MAGNETORQUER FUNCTIONS
    def mt_calibrate(self):
        """Calibrate magnetorquers"""
        #logger.info("Calibrating magnetorquers")
        pass

    def mt_monitor(self, log=False):
        """Monitor magnetorquers"""
        if log:
            logger.info("Monitoring magnetorquers")
        
        directions = {"current_x": "x", "current_y": "y", "current_z": "z"}
        self.sensor_data["magnetorquer"] = dict()
        for name,axis in directions.items():
            self.sensor_data["magnetorquer"][axis] = self.node.od["adcs"]["magnetorquer_" +name].value
            self.actuator_feedback["mt_"+axis] = self.node.od["adcs"]["magnetorquer_"+name].value


    def mt_control(self, log=False):
        """Send control signal to magnetorquers"""
        logger.info("Sending control signal to magnetorquers")
        controller_map = {"mt_x": "x", "mt_y": "y", "mt_z":"z"}

        for key, val in controller_map.items():
            if log:
                logger.info(f"Sending {self.control_signals[key]} to {key}")
            self.write_sdo('adcs', 'magnetorquer', f'current_{val}_setpoint', self.control_signals[key])

    
    # REACTION WHEEL FUNCTIONS
    def rw_apply_state(self, rw_name, state):
        self.write_sdo(rw_name, 'requested', 'state', state)
        # calibration currently relies on delay
        # do not wait for rw to enter state, handle externally
        sleep(1)
    

    def rw_calibrate(self, num_rws=4):
        #logger.info("Calibrating reaction wheels")
        
        # assumes reaction wheels are named "rw_x" where x is a number greater than or equal to 1
        get_rw_state = lambda rw_num: self.node.od[rw_name]["ctrl_stat_current_state"].value
        get_rw_error = lambda rw_name: self.node.od[rw_name]["ctrl_stat_errors"].value
        
        # this is what we want
        list_of_rw_numbers = range(1, num_rws+1)
        # This is for testing, use active RWs only
        list_of_rw_numbers = [1]
        list_of_rw_names = ["rw_"+str(num) for num in list_of_rw_numbers]

        def monitor_until_next(rw_name, next_state, delay=1, cycles=10):
            # assumes you have already set the state
            # monitors until objective state is complete
            # for example, objective_state = idle
            # can be used to check when a calibration is done
            # for example, objective_state = calibration
            # can be used to check when a RW actually starts calibrating

            this_state = get_rw_state(rw_name)
            logger.info(f"{rw_name}: current state {this_state}, waiting for state to become {next_state}")

            # state 2 is a system error
            if this_state == RW_State.SYSTEM_ERROR:
                logger.error(f"SYSTEMD ERROR FOR {rw_name}, REBOOT!")
                logger.error("RW {} ERROR BITMAP: {}".format(rw_name, get_rw_error(rw_name)))
                return 1

            # state 3 is a controller error
            if this_state == RW_State.CONTROLLER_ERROR:
                logger.error(f"CONTROLLER ERROR FOR {rw_name}, REBOOT!")
                logger.error("RW {} ERROR BITMAP: {}".format(rw_name, get_rw_error(rw_name)))
                return 1

            sleep(delay)
            
            while (this_state:=get_rw_state(rw_name)) != next_state:
                logger.info(f"{rw_name}: current state {this_state}, waiting for state to become {next_state}")

                # state 2 is a system error
                if this_state == RW_State.SYSTEM_ERROR:
                    logger.error(f"SYSTEMD ERROR FOR {rw_name}, REBOOT!")
                    logger.error("RW {} ERROR BITMAP: {}".format(rw_name, get_rw_error(rw_name)))
                    return 1

                # state 3 is a controller error
                if this_state == RW_State.CONTROLLER_ERROR:
                    logger.error(f"CONTROLLER ERROR FOR {rw_name}, REBOOT!")
                    logger.error("RW {} ERROR BITMAP: {}".format(rw_name, get_rw_error(rw_name)))
                    return 1

                sleep(delay)

            return 0



            # If states are completed, ignore
            # if system error or controller error
                # reboot the system
                # send reboot request
                # reset states completed
                # reset state history
                # increase number of attempts
            # if current_attempt but still idle, send control signal again 
            # if current_attempt = current state: wait

            # if idle and last state was the current attempt, it completed

        

        # REBOOT ALL REACTION WHEELS
        # For each reaction wheel:
            # Reboot the reaction wheel

            # For each calibration state:
                # Do the calibration
                # If it fails,
                # Reboot and start from zero

        
        # REBOOT ALL REACTION WHEELS
        for rw_name in list_of_rw_names:
            yay = False
            while not yay:
                logger.info("REBOOTING: {rw_name}")
                # self.write_sdo(rw_name, 'reboot', 'request', 1)
                logger.info(f"Waiting for {rw_name} to reboot")
                
                for ii in range(5):
                    this_state = get_rw_state(rw_name)
                    logger.info(f"{rw_name}: current state {this_state}")
                    sleep(1)
                
                if monitor_until_next(rw_name, RW_State.IDLE) == 1:
                    continue
                sleep(1)
                
                # send calibration state 1
                logger.info("Starting calibration for encoder direction")
                self.rw_apply_state(rw_name, RW_State.ENCODER_DIR_CAL)
                sleep(1)
                if monitor_until_next(rw_name, RW_State.ENCODER_DIR_CAL) == 1:
                    continue
                sleep(1)
                # If it returns to idle ok (0), it calibrated
                if monitor_until_next(rw_name, RW_State.IDLE) == 1:
                    continue
                sleep(1)

                # send calibration state 2
                logger.info("Starting calibration for encoder offset")
                self.rw_apply_state(rw_name, RW_State.ENCODER_OFFSET_CAL)
                sleep(1)
                if monitor_until_next(rw_name, RW_State.ENCODER_OFFSET_CAL) == 1:
                    continue
                sleep(1)
                # If it returns to idle ok (0), it calibrated
                if monitor_until_next(rw_name, RW_State.IDLE) == 1:
                    continue
                sleep(1)

                # If nothing threw an error, then go to next wheel
                yay = True


        sleep(5)

        
        # set velocity control
        logger.info("CALIBRATION DONE, SETTING TO A CONTROL MODE")

        sleep(5)
        control_type = RW_State.VEL_CONTROL
        for rw_name in list_of_rw_names:
            logger.info(f"Setting {rw_name} to {control_type} control")
            sleep(1)
            self.write_sdo(rw_name, 'requested', 'state', control_type)
            sleep(4)

        sleep(2)

        return 0

    def rw_monitor(self, num_rws=4, log=False):
        """Retreives reaction wheel states"""
        logger.info("Monitoring reaction wheels")
        
        temp_data = dict()

        endpoints = ['motor_velocity', 'motor_current', 'bus_current', 'bus_voltage']
        for rw_name in ["rw_" + str(num) for num in range(1, num_rws+1)]:
            # rw_name is defined, rw_state is defined via walrus

            logger.info("RW NAME: {}  RW STATE: {}".format(rw_name,rw_state:=self.node.od[rw_name]["ctrl_stat_current_state"].value))
            
            # state 2 is a system error
            if rw_state == RW_State.SYSTEM_ERROR:
                logger.error(f"SYSTEMD ERROR FOR {rw_name}, REBOOT!")
            
            # state 3 is a controller error
            if rw_state == RW_State.CONTROLLER_ERROR:
                logger.error(f"CONTROLLER ERROR FOR {rw_name}, ATTEMPTING TO CLEAR ERRORS")
                self.rw_apply_state(rw_name, RW_State.CLEAR_ERRORS)
                sleep(2)
                self.rw_apply_state(rw_name, RW_State.VEL_CONTROL)
                sleep(2)

            if rw_state == RW_State.SYSTEM_ERROR or rw_state == RW_State.CONTROLLER_ERROR:
                logger.error("RW {} ERROR BITMAP: {}".format(rw_name, self.node.od[rw_name]['ctrl_stat_errors'].value))

            self.sensor_data[rw_name] = {endpoint: self.node.od[rw_name][endpoint].value for endpoint in endpoints}
            self.actuator_feedback[rw_name] = self.node.od[rw_name]['motor_velocity'].value

            temp_data[rw_name] = {num: self.node.od[rw_name]['temperature_sensor_'+str(num)].value for num in range(1, 4)}
            logger.info(f"{rw_name} has temps {temp_data[rw_name]}")

    def rw_control(self, num_rws=4, log=False):
        """Sends the control signal to the reaction wheels"""
        
        if self.calibrating:
            return

        # also check for state
        logger.info("Sending control signal to reaction wheels")
        

        # this is what we want
        list_of_rw_numbers = range(1, num_rws+1)
        # This is for testing, use active RWs only
        list_of_rw_numbers = [1]

        list_of_rw_names = ["rw_"+str(num) for num in list_of_rw_numbers]

        for rw_name in list_of_rw_names:
            #logger.info(self.node.od[rw_name]["ctrl_stat_current_state"].value)
            # if the wheel is not in the correct state, skip
            if (self.node.od[rw_name]["ctrl_stat_current_state"].value != RW_State.VEL_CONTROL):
                logger.warning(f"Reaction Wheel {rw_name} does not appear to be in velocity control")
                continue

            self.write_sdo(rw_name, 'signals', 'setpoint', self.control_signals[rw_name])
        pass





    # Other attitude determination functions
    
    # GPS FUNCTIONS
    def gps_monitor(self, log=False):
        """Monitors the GPS readings"""
        #logger.debug("Monitoring GPS")
        if log:
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


