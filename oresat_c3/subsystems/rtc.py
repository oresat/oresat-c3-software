"""Common RTC functions."""

import os
import struct
from datetime import datetime, timezone
from fcntl import ioctl
from time import CLOCK_REALTIME, clock_settime, time

from olaf import logger


def get_rtc_time() -> float:
    """
    Get the RTC time.

    Returns
    -------
    float:
        The RTC time or -1.0 on error.
    """

    rtc_time_path = "/sys/class/rtc/rtc0/since_epoch"
    if not os.path.exists(rtc_time_path):
        logger.error("RTC does not exist")
        return -1.0

    with open(rtc_time_path, "r") as f:
        ts = float(f.read())

    return ts


def set_rtc_time(ts: float):
    """
    Set the RTC time.

    Note: All times older than January 1, 2000 are round upi to Januay 1, 2000 at midmight.

    Parameters
    -----------
    float: ts
        The timestamp to set the RTC to.
    """

    rtc_path = "/dev/rtc"
    if not os.path.exists(rtc_path):
        logger.error("RTC does not exist")
        return
    if os.geteuid() != 0:
        logger.error("failed to set RTC time due to permission error")
        return

    if ts < 946713600:  # Januay 1, 2000 midnight
        values = (0, 0, 0, 1, 0, 100, 0, 0, 0)
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # last 3 values (wday, yday, isdst) are unused
        values = (dt.second, dt.minute, dt.hour, dt.day, dt.month - 1, dt.year - 1900, 0, 0, 0)
    raw = struct.pack("9i", *values)
    with open(rtc_path) as f:
        ioctl(f, 0x4024700A, raw)  # magic number is the ioctl request code to set rtc time


def set_rtc_time_to_system_time():
    """
    Set the RTC time to the system time.
    """

    if os.geteuid() != 0:
        logger.error("failed to set RTC time from system time due to permission error")
    else:
        set_rtc_time(time())


def set_system_time_to_rtc_time():
    """
    Set the system time to the RTC time.
    """

    if os.geteuid() != 0:
        logger.error("failed to set system time from RTC time due to permission error")
    else:
        ts = get_rtc_time()
        if ts < 0:
            logger.error("RTC does not exist")
        else:
            clock_settime(CLOCK_REALTIME, ts)
