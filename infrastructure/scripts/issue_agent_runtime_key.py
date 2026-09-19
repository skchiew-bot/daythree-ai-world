"""Issues, or revokes, a scoped `agent_runtime` API key for one tenant (ADR-010 C2,
T1-F15). Ships with this PR for the test suite's use only -- the operator runs it
themselves, later, against their own database; this build does not run it against the
live tenant and does not create the first key for it.

Rotation is issue-new-then-revoke-old, WITH an overlap window: `issue()` never revokes
anything by itself, so running it again for a tenant that already has a live key leaves
BOTH valid (`AgentRuntimePrincipal`'s own docstring: rate limits are keyed per key id,
not just per user, precisely so two overlapping keys don't share one budget). Once the
new key is confirmed working, revoke the old one explicitly by id with `--revoke`.

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
    python infrastructure/scripts/issue_agent_runtime_key.py --tenant-code daythree-hq --revoke <key-id>
"""
from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid
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


async def _get_tenant(session, tenant_code: str) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.code == tenant_code))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise SystemExit(f"No tenant with code '{tenant_code}' exists.")
    return tenant


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


async def issue(tenant_code: str, *, label: str) -> str:
    """Always additive -- never revokes an existing key. Safe to call again for a
    tenant that already has a live key: rotation is issue-new-then-revoke-old, and the
    old key stays valid until a separate `revoke(...)` call names it."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        tenant = await _get_tenant(session, tenant_code)
        user = await _ensure_service_user(session, tenant)
        token = await _issue_key(session, user, label)
        await session.commit()
        return token


async def revoke(tenant_code: str, key_id: str) -> None:
    """Revokes exactly one key by id, scoped to this tenant's own service user so a
    typo'd id can never revoke a different tenant's key."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        tenant = await _get_tenant(session, tenant_code)
        user = await _ensure_service_user(session, tenant)
        try:
            parsed_key_id = uuid.UUID(key_id)
        except ValueError:
            raise SystemExit(f"'{key_id}' is not a valid key id.") from None
        key = await session.get(AgentRuntimeApiKey, parsed_key_id)
        if key is None or key.user_id != user.id:
            raise SystemExit(f"No key '{key_id}' exists for tenant '{tenant_code}'.")
        if key.revoked_at is None:
            key.revoked_at = datetime.now(timezone.utc)
            await session.commit()
        logger.info("agent_runtime_api_key_revoked", key_id=key_id, tenant_code=tenant_code)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-code", required=True)
    parser.add_argument("--label", default="issued via issue_agent_runtime_key.py")
    parser.add_argument(
        "--revoke", metavar="KEY_ID", default=None,
        help="Revoke this key id for the tenant instead of issuing a new one.",
    )
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

    if args.revoke is not None:
        asyncio.run(revoke(args.tenant_code, args.revoke))
        print(f"Revoked key {args.revoke} for tenant {args.tenant_code}.")
        return

    token = asyncio.run(issue(args.tenant_code, label=args.label))
    print(token)


if __name__ == "__main__":
    main()
