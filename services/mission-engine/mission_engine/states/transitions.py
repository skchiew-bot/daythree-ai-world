"""Explicit state-transition tables for Mission and Task (spec §8.6/§8.7).

An invalid transition raises rather than silently no-opping or clamping to the nearest
valid state — spec §4 rule 15 "no silent fallback". This is what a caller unit-tests
against directly, independent of any DB.
"""
from __future__ import annotations

from contracts.enums import MissionStatus, TaskStatus


class InvalidTransition(Exception):
    def __init__(self, entity: str, current: str, target: str):
        self.entity = entity
        self.current = current
        self.target = target
        super().__init__(f"Invalid {entity} transition: {current} -> {target}")


MISSION_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.draft: frozenset({MissionStatus.ready, MissionStatus.cancelled}),
    MissionStatus.ready: frozenset({MissionStatus.running, MissionStatus.cancelled}),
    MissionStatus.running: frozenset(
        {MissionStatus.paused, MissionStatus.completed, MissionStatus.failed, MissionStatus.cancelled}
    ),
    MissionStatus.paused: frozenset({MissionStatus.running, MissionStatus.cancelled}),
    MissionStatus.failed: frozenset(),
    MissionStatus.completed: frozenset(),
    MissionStatus.cancelled: frozenset(),
}

TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.queued: frozenset({TaskStatus.running, TaskStatus.cancelled}),
    TaskStatus.running: frozenset(
        {TaskStatus.waiting, TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}
    ),
    TaskStatus.waiting: frozenset({TaskStatus.running, TaskStatus.failed, TaskStatus.cancelled}),
    TaskStatus.failed: frozenset({TaskStatus.queued}),  # retry re-queues a failed task
    TaskStatus.completed: frozenset(),
    TaskStatus.cancelled: frozenset(),
}


def validate_mission_transition(current: MissionStatus, target: MissionStatus) -> None:
    if target not in MISSION_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition("mission", current.value, target.value)


def validate_task_transition(current: TaskStatus, target: TaskStatus) -> None:
    if target not in TASK_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition("task", current.value, target.value)
