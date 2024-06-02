from enum import IntEnum

from .cfc_capture import CfcCaptureMode
from .gps_time_sync import GpsTimeSyncMode
from .oresat_live import OreSatLiveMode
from .star_tracker_capture import StarTrackerCaptureMode
from .update import UpdateMode

MODES = {
    0x0: None,  # standby
    0x1: UpdateMode,
    0x2: GpsTimeSyncMode,
    0x3: CfcCaptureMode,
    0x4: StarTrackerCaptureMode,
    0x5: OreSatLiveMode,
}
