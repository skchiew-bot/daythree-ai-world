from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from artifact_service.storage.object_store import ObjectStore
from common.config import Settings, get_settings
from common.db.models import Artifact, Mission, User
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404
from api.dependencies.db import get_db_session
from api.dependencies.object_store import get_object_store
from api.schemas.artifacts import ArtifactDownloadResponse, ArtifactResponse

router = APIRouter(prefix="/api/v1", tags=["artifacts"])


@router.get("/missions/{mission_id}/artifacts", response_model=list[ArtifactResponse])
async def list_mission_artifacts(
    mission_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[Artifact]:
    mission = await get_tenant_scoped_or_404(session, Mission, mission_id, user.tenant_id)
    if mission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mission not found.")
    result = await session.execute(select(Artifact).where(Artifact.mission_id == mission_id))
    return list(result.scalars().all())


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> Artifact:
    artifact = await get_tenant_scoped_or_404(session, Artifact, artifact_id, user.tenant_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")
    return artifact


@router.get("/artifacts/{artifact_id}/download", response_model=ArtifactDownloadResponse)
async def download_artifact(
    artifact_id: EntityId,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    object_store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
) -> ArtifactDownloadResponse:
    """Never a public link (spec §23) — a short-lived signed URL only, scoped to a
    tenant member who can already see the artifact's metadata."""
    artifact = await get_tenant_scoped_or_404(session, Artifact, artifact_id, user.tenant_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found.")

    bucket_prefix = f"s3://{settings.object_store_bucket}/"
    key = artifact.storage_uri.removeprefix(bucket_prefix)
    url = await object_store.generate_presigned_download_url(key)
    return ArtifactDownloadResponse(download_url=url, expires_in_seconds=settings.object_store_signed_url_ttl_seconds)
