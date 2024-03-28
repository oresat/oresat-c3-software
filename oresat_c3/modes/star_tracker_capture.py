"""Star tracker capture mode."""

from enum import IntEnum

from ._mode import AdcsMode, AdcsPointAxis, Mode


class StarTrackerCaptureState(IntEnum):
    START = 1
    CAPTURE = 2


class StarTrackerCaptureMode(Mode):
    """Star tracker capture mode."""

    ADCS_MODE = AdcsMode.POINT
    ADCS_AXIS = AdcsPointAxis.POS_Y
    ARGS_FMT = "<bf3i"

    def __init__(self, captures: int, delay: int, ecef_x: int, ecef_y: int, ecef_z: int):
        """
        Parameters
        ----------
        captures: uint8
            Number of captures to take
        delay: float
            Delay between captures in seconds
        tec: bool
            With or without TEC
        ecef_x: int32
            ECEF X coordinate in cm
        ecef_y: int32
            ECEF Y coordinate in cm
        ecef_z: int32
            ECEF Z coordinate in cm
        """
        super().__init__(["star_tracker_1"], [ecef_x, ecef_y, ecef_z])

        self.captures = captures
        self.delay = delay
        self.booting = True

    def on_setup(self):
        self.node.sdo_write("star_tracker", "camera", "status", "standby")
        self.node.sdo_write("star_tracker", "camera", "num_of_images", self.captures)
        self.node.sdo_write("star_tracker", "camera", "delay", self.delay)

    def on_loop(self):
        r = True

        if self.status == StarTrackerCaptureState.CAPTURE:
            st_status = self.node.sdo_read("star_tracker", "camera", "status")
            if st_status == "booting":
                self.node.sdo_write("star_tracker", "camera", "status", "capture")
                self.booting = False
            elif st_status == "standby":
                r = False

        sleep(1)
        return r
