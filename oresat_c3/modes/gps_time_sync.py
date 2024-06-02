"""GPS time sync mode."""

from enum import Enum, unique
from time import monotonic

from olaf import logger

from ._mode import Mode


@unique
class GpsTimeSyncModeState(Enum):
    """
    .. mermaid::
        stateDiagram-v2
            [*] --> STANDBY
            STANDBY --> SEARCHING
            SEARCHING --> LOCKED: GPS card has GPS lock
            SEARCHING --> TIMED_OUT
            LOCKED --> SYNCING: Waiting for GPS card to sync its time
            LOCKED --> TIMED_OUT
            SYNCING --> SYNCD: C3 is syncing to gps time
            SYNCING --> TIMED_OUT
            SYNCD --> [*]: C3 has syncd to GPS time
            TIMED_OUT --> [*]: timeout for GPS time sync has been reached
    """

    STANDBY = 0
    SEARCHING = 1
    LOCKED = 2
    SYNCING = 3
    SYNCD = 4
    TIMED_OUT = 5
    ERROR = 0xFF


class GpsTimeSyncMode(Mode):
    """GPS time sync mode."""

    CARD = "gps"
    REQUIRED_CARDS = [CARD]

    def on_setup(self):

        self.enable_nodes([self.CARD])

        self.node.od_write(self.CARD, "locked", False)
        self.node.od_write(self.CARD, "time_syncd", False)

    def on_run(self):

        start_time = monotonic()
        search_timeout = 900
        time_syncd_timeout = 60

        # wait for gps lock
        while self.node.od_read(self.CARD, "locked") is False:
            if monotonic() > start_time + search_timeout:
                return
            self.sleep_ms(1000)
        logger.info("gps card syncd has gps lock")

        # wait for gps card time sync
        while self.node.od_read(self.CARD, "time_syncd") is False:
            if monotonic() > start_time + time_syncd_timeout:
                return
            self.sleep_ms(1000)
        logger.info("gps card has syncd to gps time at uptime")

        # tigger time sync over CAN
        logger.info("syncing to gps time")
        self.node.send_sync()

        logger.info("syncd to gps time")
