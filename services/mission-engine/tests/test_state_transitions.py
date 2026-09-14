import pytest

from contracts.enums import MissionStatus, TaskStatus
from mission_engine.states.transitions import (
    InvalidTransition,
    validate_mission_transition,
    validate_task_transition,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "current,target",
    [
        (MissionStatus.draft, MissionStatus.ready),
        (MissionStatus.ready, MissionStatus.running),
        (MissionStatus.running, MissionStatus.completed),
        (MissionStatus.running, MissionStatus.failed),
        (MissionStatus.running, MissionStatus.paused),
        (MissionStatus.paused, MissionStatus.running),
    ],
)
def test_valid_mission_transitions_are_accepted(current, target):
    validate_mission_transition(current, target)  # must not raise


@pytest.mark.parametrize(
    "current,target",
    [
        (MissionStatus.draft, MissionStatus.running),  # can't skip "ready"
        (MissionStatus.completed, MissionStatus.running),  # terminal state
        (MissionStatus.cancelled, MissionStatus.draft),
        (MissionStatus.failed, MissionStatus.completed),
    ],
)
def test_invalid_mission_transitions_are_rejected(current, target):
    with pytest.raises(InvalidTransition):
        validate_mission_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.queued, TaskStatus.running),
        (TaskStatus.running, TaskStatus.completed),
        (TaskStatus.running, TaskStatus.failed),
        (TaskStatus.failed, TaskStatus.queued),  # retry
    ],
)
def test_valid_task_transitions_are_accepted(current, target):
    validate_task_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (TaskStatus.completed, TaskStatus.running),
        (TaskStatus.queued, TaskStatus.completed),  # can't skip "running"
        (TaskStatus.cancelled, TaskStatus.queued),
    ],
)
def test_invalid_task_transitions_are_rejected(current, target):
    with pytest.raises(InvalidTransition):
        validate_task_transition(current, target)
