"""Artifact commit orchestration: uploads bytes to object storage, then commits the
metadata row idempotently (spec §14).

Two layers of protection against a duplicate committed artifact:
1. Check-first: `find_committed` is queried before doing any work; if a prior attempt
   already committed this (task_id, artifact_type, logical_output_slot), we return it
   immediately — this is what makes a worker restart after a crash safe (TC-P0-007).
2. Insert-with-fallback: the DB's `uq_artifacts_idempotent_commit` constraint is the
   real guarantee for the narrow race where two attempts both pass the check above at
   the same time. The insert runs inside a SAVEPOINT (`begin_nested`) so a conflict
   only rolls back this one insert — never the caller's outer transaction (which may
   also be updating the task row and appending events in the same unit of work).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Artifact
from common.hashing import sha256_hex
from contracts.enums import ArtifactType
from contracts.ids import EntityId

from artifact_service.metadata.repository import find_committed
from artifact_service.storage.object_store import ObjectStore


@dataclass
class CommitResult:
    artifact: Artifact
    newly_created: bool


async def commit_artifact(
    session: AsyncSession,
    object_store: ObjectStore,
    *,
    tenant_id: EntityId,
    mission_id: EntityId,
    task_id: EntityId,
    agent_id: EntityId,
    agent_version_id: EntityId,
    artifact_type: ArtifactType,
    title: str,
    content: bytes,
    mime_type: str,
    logical_output_slot: str = "primary",
    metadata: Optional[dict[str, Any]] = None,
) -> CommitResult:
    existing = await find_committed(
        session, task_id=task_id, artifact_type=artifact_type, logical_output_slot=logical_output_slot
    )
    if existing is not None:
        return CommitResult(artifact=existing, newly_created=False)

    content_hash = sha256_hex(content)
    storage_key = (
        f"{tenant_id}/{mission_id}/{task_id}/{artifact_type.value}/"
        f"{logical_output_slot}/v1-{content_hash[:16]}"
    )
    storage_uri = await object_store.put_object(storage_key, content, mime_type)

    artifact = Artifact(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_id=task_id,
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        artifact_type=artifact_type.value,
        logical_output_slot=logical_output_slot,
        title=title,
        storage_uri=storage_uri,
        content_hash=content_hash,
        mime_type=mime_type,
        version=1,
        artifact_metadata=metadata or {},
    )
    session.add(artifact)

    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        existing = await find_committed(
            session, task_id=task_id, artifact_type=artifact_type, logical_output_slot=logical_output_slot
        )
        if existing is None:
            raise  # a real constraint violation unrelated to idempotency — do not swallow it
        return CommitResult(artifact=existing, newly_created=False)

    return CommitResult(artifact=artifact, newly_created=True)
