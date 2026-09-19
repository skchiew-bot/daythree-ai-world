"""The scoped, non-human credential for the Claude Code hooks (ADR-010 C2, T1-F4/T1-F15).

Deliberately a SEPARATE dependency from `api.dependencies.auth` -- `get_current_user`,
`require_role` and the JWT path are not touched by this feature at all. The wire format is
`dtk_<key id, 32 hex chars>_<secret>`; only `sha256(secret)` is ever stored (unsalted sha256
is acceptable here ONLY because the secret is 256 bits from `secrets.token_urlsafe(32)` --
there is nothing to brute-force or rainbow-table, unlike a human password, which stays
bcrypt in `api.dependencies.auth`). Revocation and expiry are read fresh on every call --
no cache -- so revocation takes effect immediately.
"""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AgentRuntimeApiKey, Tenant, User
from common.hashing import sha256_hex
from contracts.enums import TenantStatus, UserRole, UserStatus
from contracts.ids import EntityId

from api.dependencies.auth import get_current_user
from api.dependencies.db import get_db_session


@dataclass(frozen=True)
class AgentRuntimePrincipal:
    """The resolved caller for the agent-runtime router: the service `User` row plus
    the specific `AgentRuntimeApiKey` id used, so routes can rate-limit per key (not
    just per user) -- rotation deliberately keeps the old key valid for a short window
    (issue-new-then-revoke-old), so a tenant can briefly have two live keys."""

    user: User
    key_id: EntityId

_agent_runtime_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid, expired or revoked agent-runtime API key.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _parse_key(token: str) -> tuple[uuid.UUID, str] | None:
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "dtk":
        return None
    key_id_hex, secret = parts[1], parts[2]
    if not secret:
        return None
    try:
        return uuid.UUID(hex=key_id_hex), secret
    except ValueError:
        return None


async def get_agent_runtime_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_agent_runtime_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> AgentRuntimePrincipal:
    if credentials is None:
        raise _UNAUTHORIZED
    parsed = _parse_key(credentials.credentials)
    if parsed is None:
        raise _UNAUTHORIZED
    key_id, secret = parsed

    key_row = await session.get(AgentRuntimeApiKey, key_id)
    # The digest comparison always runs, even when no row matched (against a fixed
    # dummy hash) -- otherwise "no such key id" returns before the hash compare while
    # "wrong secret" always pays it, and hmac.compare_digest's own constant-time
    # guarantee would be undermined by a control-flow timing gap one layer up.
    stored_hash = key_row.key_hash if key_row is not None else sha256_hex("no-such-key-timing-safety-placeholder")
    secret_ok = hmac.compare_digest(sha256_hex(secret), stored_hash)
    if key_row is None or not secret_ok:
        raise _UNAUTHORIZED

    now = datetime.now(timezone.utc)
    if key_row.revoked_at is not None:
        raise _UNAUTHORIZED
    if key_row.expires_at is not None and key_row.expires_at <= now:
        raise _UNAUTHORIZED

    user = await session.get(User, key_row.user_id)
    if user is None or user.status != UserStatus.active.value or user.role != UserRole.agent_runtime.value:
        raise _UNAUTHORIZED

    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None or tenant.status != TenantStatus.active.value:
        raise _UNAUTHORIZED

    return AgentRuntimePrincipal(user=user, key_id=key_id)


def forbid_agent_runtime(user: User = Depends(get_current_user)) -> User:
    """Default-deny for the credential (T1-F3): wired onto every router except
    `health`, `auth` and `agent_runtime` itself in `routes/__init__.py`, so any route
    added later inherits the refusal automatically instead of needing its own opt-out."""
    if user.role == UserRole.agent_runtime.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The agent-runtime credential cannot access this route.",
        )
    return user
