from .abc_cmd import AbcCmd, logger
from ..subsystems.rtc import set_rtc_time, set_system_time_to_rtc_time


class RtcSetTimeCmd(AbcCmd):
    id = 14
    req_format = "I"
    res_format = "?"

    def run(self, request: tuple) -> tuple:
        (ts,) = request
        logger.info(f"EDL setting the RTC time to {ts}")
        set_rtc_time(ts)
        set_system_time_to_rtc_time()
