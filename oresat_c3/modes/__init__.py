from enum import IntEnum

from .cfc_capture import CfcCaptureMode
from .file_transfer import FileTransferMode
from .gps_time_sync import GpsTimeSyncMode
from .oresat_live import OreSatLiveMode
from .star_tracker_capture import StarTrackerCaptureMode
from .update import UpdateMode

MODES = {
    0: None,  # standby
    1: FileTransferMode,
    2: UpdateMode,
    3: GpsTimeSyncMode,
    4: CfcCaptureMode,
    5: StarTrackerCaptureMode,
    6: OreSatLiveMode,
}
