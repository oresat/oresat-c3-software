from os import geteuid
from time import time, clock_settime, CLOCK_REALTIME

from olaf import logger

from ..drivers.rv3028c7 import Rv3082c7


class Rtc:
    '''
    Wapper ontop RV-3082-C7 RTC and the system time (keeps them in sync). When a object of this
    class is made the system time will be set to the RTC time
    '''

    def __init__(self, bus_num: int, mock: bool = False):
        '''
        Parameters
        ----------
        bus_num: int
            The I2C bus number the RTC is on.
        mock: bool
            Mock the RV-3082-C7
        '''

        self._mock = mock
        if self._mock:
            logger.warning('mocking the RTC')

        self._rv3028c7 = Rv3082c7(bus_num, mock)

        # set system time to rtc time
        if not self._mock:
            if geteuid() == 0:
                ts = self._rv3028c7.unix_time
                clock_settime(CLOCK_REALTIME, ts)
                logger.info(f'setting system time to RTC time, {ts} -> {time()}')
            else:
                logger.error(f'cannot set system time to RTC time, {ts} -> {time()}, not running'
                             'as root')

    def get_time(self) -> float:
        '''
        Get the current time

        Returns
        -------
        float
            The current time from the RTC.
        '''

        return self._rv3028c7.unix_time

    def set_time(self, value: float):
        ''''
        Set the RTC and system time

        Parameters
        ----------
        float
            The time to set the RTC and system to.
        '''

        ts = time()

        # set rtc time
        self._rv3028c7.value = value
        logger.info(f'setting system time and RTC time to {value}')

        # set system time
        if not self._mock:
            if geteuid() == 0:
                ts = self._rv3028c7.unix_time
                clock_settime(CLOCK_REALTIME, ts)
            else:
                logger.error('cannot set system time, not running as root')
