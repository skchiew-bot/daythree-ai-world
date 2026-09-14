from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Artifact
from contracts.enums import ArtifactType
from contracts.ids import EntityId


async def find_committed(
    session: AsyncSession, *, task_id: EntityId, artifact_type: ArtifactType, logical_output_slot: str,
) -> Artifact | None:
    """Looks up an existing commit for this exact idempotent-commit key (spec §14).

    Deliberately does not filter on `version` — any existing row for this
    (task, type, slot) means "already committed"; Phase 0 tasks only ever commit once
    per slot, so the first row found IS the committed version.
    """
    result = await session.execute(
        select(Artifact).where(
            Artifact.task_id == task_id,
            Artifact.artifact_type == artifact_type.value,
            Artifact.logical_output_slot == logical_output_slot,
        )
    )
    return result.scalar_one_or_none()
