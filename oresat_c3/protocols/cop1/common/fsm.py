from enum import Enum, IntEnum
from typing import Callable, Generic, NamedTuple, TypeVar

from .util import logger


class CopState(Enum):
    pass


class CopEvent(IntEnum):
    pass


T = TypeVar("T", bound=CopState)
U = TypeVar("U", bound=CopEvent)


class StateMachine(Generic[T, U]):
    TRANSITION_FROM = NamedTuple("TransitionFrom", (("from_state", T), ("event", U)))
    TRANSITION_TO = NamedTuple("TransitionTo", (("to_state", T), ("actions", list[Callable])))

    def __init__(self, initial_state: T) -> None:
        self._current_state: T = initial_state
        self._transition_map: dict[StateMachine.TRANSITION_FROM, StateMachine.TRANSITION_TO] = {}

    @property
    def current_state(self) -> T:
        return self._current_state

    def process_event(self, event: U) -> None:
        logger.debug(f"Event received: {event.name}")
        transition = self._transition_map[self._current_state, event]
        for action in transition.actions:
            action()
        self.transition_to(transition.to_state)
        self._current_state = transition.to_state

    def add_transition(self, t_from: TRANSITION_FROM, t_to: TRANSITION_TO) -> None:
        self._transition_map[t_from] = t_to

    def transition_to(self, state: T) -> None:
        self._current_state = state
