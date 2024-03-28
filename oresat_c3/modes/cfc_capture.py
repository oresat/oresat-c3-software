"""CFC capture mode."""

from enum import IntEnum

import canopen

from ._mode import AdcsMode, AdcsPointAxis, Mode


class CfcCaptureState(IntEnum):
    START = 1
    CAPTURE = 2
    # STD
    SETUP = 80
    FILE_TRANSFER = 81
    CLEANUP = 82
    DONE = 83


class CfcCaptureMode(Mode):
    """CFC capture mode."""

    ADCS_MODE = AdcsMode.POINT
    ADCS_AXIS = AdcsPointAxis.POS_Z
    ARGS_FMT = "<bf?3i"

    def __init__(
        self, captures: int, delay: float, tec: bool, ecef_x: int, ecef_y: int, ecef_z: int
    ):
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
        super().__init__(["cfc_processor"], [ecef_x, ecef_y, ecef_z])

        self.captures = captures
        self.delay = delay
        self.tec = tec

    def on_setup(self):
        self.node.sdo_write("cfc", "camera", "status", "standby")
        self.node.sdo_write("cfc", "camera", "number_to_capture", self.captures)
        self.node.sdo_write("cfc", "camera", "capture_delay", self.delay)
        self.node.sdo_write("cfc", "tec", "status", self.tec)

    def on_loop(self) -> bool:
        r = True

        if self.state == CfcCaptureState.START:
            try:
                self.node.sdo_write("cfc", "camera", "status", "capture")
                self.state = CfcCaptureState.CAPTURE
            except canopen.SdoAbortedError:
                pass
        elif self.state == CfcCaptureState.CAPTURE:
            try:
                sdo_value = self.node.sdo_read("cfc", "camera", "status")
                if sdo_value == "standby":
                    self.state = CfcCaptureState.CLEANUP
            except canopen.SdoAbortedError:
                pass
        elif self.state == CfcCaptureState.CLEANUP:
            self._cleanup()
            self.state = CfcCaptureState.DONE
            r = False
        # elif self.state == CfcCaptureState.FILE_TRANSFER:

        sleep(1)
        return r

    def _cleanup(self):
        try:
            self.node.sdo_write("cfc", "tec", "status", False)
            self.node.sdo_write("cfc", "camera", "status", "off")
        except canopen.SdoAbortedError:
            pass

    def on_cleanup(self):
        self._cleanup()
