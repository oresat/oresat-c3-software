import logging
from threading import Event, Thread

from oresat_cand import ManagerNodeClient

logger = logging.getLogger(__name__)


class Service:
    def __init__(self, node: ManagerNodeClient):
        self.node = node
        self._event = Event()

    def on_loop(self):
        self.sleep(1)

    def _run(self):
        while not self._event.is_set():
            try:
                self.on_loop()
            except Exception as e:
                logger.error(
                    f"{self.__class__.__name__} unexpected exception raised by on_loop {e}"
                )
                self._event.set()
        self.stop()

    def start(self):
        thread = Thread(target=self._run, daemon=True)
        thread.start()

    def on_stop(self):
        pass

    def stop(self):
        try:
            self.on_stop()
        except Exception as e:
            logger.error(f"{self.__class__.__name__} unexpected exception raised by on_stop: {e}")

    def sleep(self, timeout: float):
        self._event.wait(timeout)

    def sleep_ms(self, timeout: float):
        self._event.wait(timeout / 1000)

    @property
    def is_running(self) -> bool:
        return not self._event.is_set()
