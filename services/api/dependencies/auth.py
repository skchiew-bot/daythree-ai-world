"""Local password auth (spec §23: "local seeded admin account acceptable" for Phase 0,
OIDC/OAuth2-ready abstraction left for later). Every state-changing route depends on
`get_current_user` plus a `require_role(...)` check — never on a client-supplied
tenant/role claim without also verifying against the DB row (spec §23 Authorization:
"Every state-changing endpoint validates: authenticated actor, tenant, role, resource
scope").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import Settings, get_settings
from common.db.models import User
from contracts.enums import UserRole, UserStatus
from contracts.ids import EntityId, parse_id

from api.dependencies.db import get_db_session

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# `bcrypt` directly, not passlib's CryptContext: passlib 1.7.x (last released 2020)
# probes `bcrypt.__about__.__version__` to detect the backend version, which bcrypt
# 4.1+/5.x no longer exposes, breaking passlib's hash() call entirely. Calling bcrypt
# directly avoids the abandoned compatibility shim altogether.
_BCRYPT_ROUNDS = 12


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("ascii"))


# A fixed, valid bcrypt hash of an unguessed-by-design string, computed once at import
# time — used by the login route to run a real bcrypt comparison even when no such
# user exists, so "no such email" and "wrong password" take the same amount of time
# and can't be distinguished by an attacker timing the response (see routes/auth.py).
DUMMY_PASSWORD_HASH = hash_password("no-such-user-timing-safety-placeholder")


def create_access_token(*, user_id: EntityId, tenant_id: EntityId, role: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


async def get_current_user(
    token: str = Depends(_oauth2_scheme),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        user_id = parse_id(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise credentials_error from exc

    user = await session.get(User, user_id)
    if user is None or user.status != UserStatus.active.value:
        raise credentials_error
    return user


def require_role(*allowed_roles: UserRole):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in {r.value for r in allowed_roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to perform this action.",
            )
        return user

    return _check


async def get_tenant_scoped_or_404(session: AsyncSession, model, object_id: EntityId, tenant_id: EntityId):
    """Fetches `model` by id, but returns None (→ the route raises 404) if it belongs
    to a different tenant — a 404 rather than 403 so cross-tenant probing can't even
    learn whether the resource exists (TC-P0-012)."""
    result = await session.execute(
        select(model).where(model.id == object_id, model.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()
