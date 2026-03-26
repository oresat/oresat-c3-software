import time
from enum import IntEnum, unique

from olaf import Service

@unique
class RWControllerState(IntEnum):
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

@unique
class ControllerErrors(IntEnum):
    CTRLR_ERR_NONE = 0
    CTRLR_ERR_INVERTER_CALIBRATION_INVALID = 1 << 0
    CTRLR_ERR_PHASE_CURRENTS_INVALID = 1 << 1
    CTRLR_ERR_PHASE_CURRENTS_MEASUREMENT_MISSING = 1 << 2
    CTRLR_ERR_PWM_TIMING_INVALID = 1 << 3
    CTRLR_ERR_PWM_TIMING_UPDATE_MISSING = 1 << 4
    CTRLR_ERR_VBUS_OVERVOLTAGE = 1 << 5
    CTRLR_ERR_VBUS_UNDERVOLTAGE = 1 << 6
    CTRLR_ERR_IBUS_OVERCURRENT = 1 << 7
    CTRLR_ERR_MOTOR_OVERCURRENT = 1 << 8
    CTRLR_ERR_MOTOR_PHASE_LEAKAGE = 1 << 9
    CTRLR_ERR_MOTOR_RESISTANCE_OUT_OF_RANGE = 1 << 10
    CTRLR_ERR_MOTOR_INDUCTANCE_OUT_OF_RANGE = 1 << 11
    CTRLR_ERR_ENCODER_READING_MISSING = 1 << 12
    CTRLR_ERR_ENCODER_ESTIMATE_MISSING = 1 << 13
    CTRLR_ERR_ENCODER_READING_INVALID = 1 << 14
    CTRLR_ERR_ENCODER_FAILURE = 1 << 15
    CTRLR_ERR_PHASE_CURRENT_USAGE_MISSING = 1 << 16
    CTRLR_ERR_PWM_TIMING_USAGE_MISSING = 1 << 17
    CTRLR_ERR_PHASE_CURRENT_LEAKAGE = 1 << 18
    CTRLR_ERR_ENCODER_READING_USAGE_MISSING = 1 << 19
    CTRLR_ERR_MOTOR_UNBALANCED_PHASES = 1 << 20
    CTRLR_ERR_MODULATION = 1 << 21

@unique
class ProcedureResult(IntEnum):
    FAIL = 0
    SUCCESS = 1

class ReactionWheelTest(Service):

    def __init__(self, mock_hw: bool = False):
        super().__init__()

    def run(self):
        # rw_1 is the only wheel in flatsat
        # calibrate
        for state in (
                RWControllerState.MOTOR_RESISTANCE_CAL,
                RWControllerState.MOTOR_INDUCTANCE_CAL,
                RWControllerState.ENCODER_DIR_CAL,
                RWControllerState.ENCODER_OFFSET_CAL
        ):
            self.node.sdo_write("rw_1", "requested", "state", state)
            time.sleep(0.5)
            while self.node.od["rw_1"]["ctrl_stat_current_state"].value == state:
                time.sleep(0.1)

            time.sleep(0.1)
            if self.node.od["rw_1"]["ctrl_stat_current_state"].value != RWControllerState.IDLE:
                if self.node.od["rw_1"]["ctrl_stat_procedure_result"].value != ProcedureResult.SUCCESS:
                    print(f"Error on {state.name}")
                    return

        # adjust velocity
        self.node.sdo_write("rw_1", "requested", "state", RWControllerState.VEL_CONTROL)
        self.node.sdo_write("rw_1", "signals", "setpoint", 5.0)

        time.sleep(2)

        self.node.sdo_write("rw_1", "signals", "setpoint", 0.0)
        time.sleep(1)
        self.node.sdo_write("rw_1", "requested", "state", RWControllerState.IDLE)

    def on_loop(self):
        if self.node.od["node_status"][0x38].value == 2 and self.node.od["node_status"][0x3C].value == 2:
            # both ADCS and RW_1 are ON
            self.run()
