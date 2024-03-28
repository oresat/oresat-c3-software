"""GPS time sync mode."""

from time import monotonic

from olaf import logger

from ._mode import Mode


class GpsTimeSyncMode(Mode):
    """GPS time sync mode."""

    def __init__(self):
        super().__init__(["gps"])

    def on_setup(self):
        self.node.od["gps"]["time_syncd"].value = False

    def on_loop(self):
        r = True

        timeout = 1200  # TODO replace value with timeout obj
        if monotonic() - self.start_time > timeout:
            if self.node.od["gps"]["time_syncd"].value:
                logger.info("syncd to gps time")
                r = False
            else:
                self.node.send_sync()
            sleep(1)
        else:
            logger.error(f"failed to recieve gps time sync PDO after {timeout} seconds")
            r = False

        return r
