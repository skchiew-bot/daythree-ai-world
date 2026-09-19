"""Issues (or rotates) a scoped `agent_runtime` API key for one tenant (ADR-010 C2,
T1-F15). Ships with this PR for the test suite's use only -- the operator runs it
themselves, later, against their own database; this build does not run it against the
live tenant and does not create the first key for it.

Safety:
  - Refuses a non-local `DATABASE_URL` unless `--allow-remote` is passed explicitly --
    this script prints a live secret to stdout, and that must never happen by accident
    against a shared/production database.
  - The secret is printed to stdout exactly once and is never passed to `structlog` or
    written to any file this script controls.
  - The service `User` row's password is a real bcrypt hash of discarded random bytes
    (never a literal string): `verify_password` must be able to run a real comparison
    against it without raising, so a wrong-password attempt on `POST /auth/login` for
    this email 401s instead of 500ing the public login route.

Usage:
    python infrastructure/scripts/issue_agent_runtime_key.py --tenant-code daythree-hq
    python infrastructure/scripts/issue_agent_runtime_key.py --tenant-code daythree-hq --rotate
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from common.config import get_settings
from common.db.models import AgentRuntimeApiKey, Tenant, User
from common.db.session import get_sessionmaker
from common.hashing import sha256_hex
from contracts.enums import UserRole, UserStatus
from contracts.ids import new_id

logger = structlog.get_logger(__name__)

_LOCAL_HOST_MARKERS = ("localhost", "127.0.0.1")


def _is_local_database_url(url: str) -> bool:
    return any(marker in url for marker in _LOCAL_HOST_MARKERS)


def _service_email(tenant_code: str) -> str:
    return f"agent-runtime+{tenant_code}@daythree.local"


async def _ensure_service_user(session, tenant: Tenant) -> User:
    from api.dependencies.auth import hash_password

    email = _service_email(tenant.code)
    result = await session.execute(select(User).where(User.tenant_id == tenant.id, User.email == email))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    # Discarded random bytes, never a literal like "!" -- a literal would make
    # `verify_password` raise on a malformed hash and 500 the public login route
    # (T1-F8) the first time anyone mistypes a password for this address.
    unusable_password = secrets.token_urlsafe(48)
    user = User(
        id=new_id(), tenant_id=tenant.id, email=email, display_name=f"Agent Runtime ({tenant.code})",
        role=UserRole.agent_runtime.value, status=UserStatus.active.value,
        password_hash=hash_password(unusable_password),
    )
    session.add(user)
    await session.flush()
    logger.info("agent_runtime_service_user_created", tenant_code=tenant.code, user_id=str(user.id))
    return user


async def _issue_key(session, user: User, label: str) -> str:
    secret = secrets.token_urlsafe(32)
    key = AgentRuntimeApiKey(
        id=new_id(), user_id=user.id, key_hash=sha256_hex(secret), label=label,
    )
    session.add(key)
    await session.flush()
    logger.info("agent_runtime_api_key_issued", key_id=str(key.id), label=label)  # never the secret
    return f"dtk_{key.id.hex}_{secret}"


async def _revoke_existing_keys(session, user: User) -> int:
    result = await session.execute(
        select(AgentRuntimeApiKey).where(AgentRuntimeApiKey.user_id == user.id, AgentRuntimeApiKey.revoked_at.is_(None))
    )
    rows = list(result.scalars().all())
    now = datetime.now(timezone.utc)
    for row in rows:
        row.revoked_at = now
    await session.flush()
    return len(rows)


async def issue(tenant_code: str, *, label: str, rotate: bool) -> str:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(Tenant).where(Tenant.code == tenant_code))
        tenant = result.scalar_one_or_none()
        if tenant is None:
            raise SystemExit(f"No tenant with code '{tenant_code}' exists.")

        user = await _ensure_service_user(session, tenant)
        if rotate:
            revoked = await _revoke_existing_keys(session, user)
            logger.info("agent_runtime_api_keys_revoked", tenant_code=tenant_code, count=revoked)
        token = await _issue_key(session, user, label)
        await session.commit()
        return token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--label", default="issued via issue_agent_runtime_key.py")
    parser.add_argument("--rotate", action="store_true", help="Revoke this tenant's existing keys first.")
    parser.add_argument(
        "--allow-remote", action="store_true",
        help="Required to run against a DATABASE_URL that is not localhost/127.0.0.1.",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not args.allow_remote and not _is_local_database_url(settings.database_url):
        print(
            "Refusing to run against a non-local DATABASE_URL without --allow-remote "
            "-- this script prints a live secret to stdout.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    token = asyncio.run(issue(args.tenant_code, label=args.label, rotate=args.rotate))
    print(token)


if __name__ == "__main__":
    main()
