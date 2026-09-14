"""Slot-math unit tests for ADR-009's apartment layout. No DB, no I/O."""
from __future__ import annotations

import pytest

from common.rooms import lowest_free_slot, room_to_slot, slot_to_room

pytestmark = pytest.mark.unit


def test_first_occupant_gets_floor_1_room_1():
    assert slot_to_room(0) == (1, 1)


def test_fourth_occupant_gets_floor_1_room_4():
    assert slot_to_room(3) == (1, 4)


def test_fifth_occupant_gets_floor_2_room_1():
    assert slot_to_room(4) == (2, 1)


def test_twentieth_occupant_gets_floor_5_room_4():
    assert slot_to_room(19) == (5, 4)


def test_twenty_first_occupant_overflows_to_floor_6_room_1():
    """Soft-cap property (ADR-009): 20 rooms is the visual default, not a hard limit."""
    assert slot_to_room(20) == (6, 1)


def test_slot_to_room_rejects_negative_slot():
    with pytest.raises(ValueError):
        slot_to_room(-1)


def test_slot_and_room_round_trip():
    for slot in range(41):
        floor, room_index = slot_to_room(slot)
        assert room_to_slot(floor, room_index) == slot


def test_lowest_free_slot_fills_a_released_gap():
    assert lowest_free_slot({0, 1, 3}) == 2


def test_lowest_free_slot_empty_tenant_returns_zero():
    assert lowest_free_slot(set()) == 0


def test_lowest_free_slot_all_occupied_extends_past_the_block():
    assert lowest_free_slot({0, 1, 2, 3}) == 4
