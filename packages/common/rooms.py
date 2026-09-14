"""Pure slot math for the agent-room apartment (ADR-009). No I/O, no DB — the
allocator and its unit tests share this one source of truth instead of each
re-deriving the floor/room arithmetic.
"""
from __future__ import annotations

ROOMS_PER_FLOOR = 4
DEFAULT_FLOOR_COUNT = 5


def slot_to_room(slot: int) -> tuple[int, int]:
    """0-indexed occupancy slot -> 1-indexed (floor, room_index).

    slot 0 -> (1, 1); slot 3 -> (1, 4); slot 4 -> (2, 1). No ceiling: slot 20 (the
    21st occupant) overflows to (6, 1) rather than being rejected — the apartment's
    20-room/5-floor size is a soft visual default, not a hard cap (ADR-009).
    """
    if slot < 0:
        raise ValueError("slot must be >= 0")
    floor = slot // ROOMS_PER_FLOOR + 1
    room_index = slot % ROOMS_PER_FLOOR + 1
    return floor, room_index


def room_to_slot(floor: int, room_index: int) -> int:
    return (floor - 1) * ROOMS_PER_FLOOR + (room_index - 1)


def lowest_free_slot(occupied: set[int]) -> int:
    slot = 0
    while slot in occupied:
        slot += 1
    return slot
