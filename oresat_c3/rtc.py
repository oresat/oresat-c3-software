from time import time


class Rtc:

    def __init__(self, mock: bool = False):

        self._mock = mock

    def get_time(self) -> float:

        if self._mock:
            return time()
        else:
            raise NotImplementedError

    def set_time(self, time: float):

        if not self._mock:
            raise NotImplementedError
