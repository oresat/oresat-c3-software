from collections import deque
from typing import TypeVar

T = TypeVar("T")


class BoundedDeque(deque[T]):
    def __init__(self, maxlen: int) -> None:
        super().__init__()
        self._maxlen = maxlen

    def append(self, item: T, force: bool = False) -> bool:
        if not force and len(self) >= self._maxlen:
            return False
        super().append(item)
        return True

    def appendleft(self, item: T) -> bool:
        if len(self) >= self._maxlen:
            return False
        super().appendleft(item)
        return True
