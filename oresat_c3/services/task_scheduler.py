"""'
Task Service
"""

from dataclasses import dataclass
from enum import IntEnum
from time import time
from typing import List

from olaf import Service, set_cpufreq

from ..modes import MODES
from .node_manager import NodeManagerService


@dataclass
class Task:
    """Task info."""

    mode_id: int
    start_time: int
    end_time: int
    mode_args: bytes

    def __lt__(self, other) -> bool:
        return other.start_time < self.start_time

    def __gt__(self, other) -> bool:
        return not self.__lt__(other)


class TaskState(IntEnum):
    """Task state."""

    STANDBY = 1
    """No current task."""
    SETUP = 2
    """Setting up for a task (powering on cards)."""
    STARTING = 3
    """Starting the task."""
    ACTIVE = 4
    """Task is active."""
    STOPING = 5
    """Stopping the task."""
    TEARDOWN = 6
    """Teardown of the task (powering down cards)."""


class TaskService(Service):
    """OreSat system mode service."""

    START_THRESHOLD_S = 300  # 5 minutes

    def __init__(self, node_manager_service: NodeManagerService):
        super().__init__()

        self._node_manager_service = node_manager_service
        self._queue: List[Task] = []

        self.task_state = TaskState.STANDBY
        """The current task state."""
        self.task = None
        """The current task"""
        self.mode = None
        """The current mode"""

        self._task_scheduler_enable_obj = False

    def on_start(self):
        set_cpufreq(300)

    def on_loop(self):
        if not self._task_scheduler_enable_obj:
            if self.task_state == TaskState.STANDBY:
                self.sleep(1)
                return
            if self.task_state == TaskState.ACTIVE:
                self.task_state = TaskState.STOPING

        if self.task_state == TaskState.STANDBY:
            if len(self._queue) > 0 and self._queue[0].start_time + self.START_THRESHOLD_S > time():
                self.task = self._queue.pop()
                self.mode = MODES[self.task.mode_id]
                self.task_state = TaskState.SETUP
        elif self.task_state == TaskState.SETUP:
            set_cpufreq(1000)
            for card in self.mode.cards:
                self._node_manager_service[card].enable()
                self.task_state = TaskState.STARTING
        elif self.task_state == TaskState.STARTING:
            self.mode.on_start()
            self.task_state = TaskState.ACTIVE
        elif self.task_state == TaskState.ACTIVE:
            if self.task.end_time == 0.0 or self.task.end_time < time():
                self.mode.on_loop()
            else:
                self.task_state = TaskState.STOPING
        elif self.task_state == TaskState.STOPING:
            self.mode.on_stop()
            self.task_state = TaskState.TEARDOWN
        elif self.task_state == TaskState.TEARDOWN:
            for card in self.mode.cards:
                self._node_manager_service[card].disable()
            set_cpufreq(300)
            self.task_state = TaskState.STANDBY

        self.sleep_ms(100)

    def on_stop(self):
        pass
