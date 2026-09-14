"""ID generation and type aliases used across every service."""
from __future__ import annotations

import uuid

EntityId = uuid.UUID


def new_id() -> EntityId:
    """Generate a new random (v4) entity id.

    UUID v4 is used rather than a sortable id (e.g. UUIDv7/ULID) because Phase 0 has no
    requirement for k-sortable primary keys and stdlib `uuid4` needs no extra dependency.
    Revisit if insert-order locality on large tables becomes a real performance concern.
    """
    return uuid.uuid4()


def parse_id(value: str) -> EntityId:
    return uuid.UUID(str(value))
