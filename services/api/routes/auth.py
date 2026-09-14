from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import Settings, get_settings
from common.db.models import User
from contracts.enums import UserStatus

from api.dependencies.auth import DUMMY_PASSWORD_HASH, create_access_token, get_current_user, verify_password
from api.dependencies.db import get_db_session
from api.schemas.auth import CurrentUserResponse, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    result = await session.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
    )

    # Always run a real bcrypt comparison, even for a nonexistent user (against a fixed
    # dummy hash) — otherwise "no such email" returns near-instantly while "wrong
    # password" pays bcrypt's cost, and that timing gap lets an attacker enumerate
    # valid emails against this endpoint without ever seeing a different status code.
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_ok = verify_password(form_data.password, password_hash)

    if user is None or user.status != UserStatus.active.value or not password_ok:
        raise invalid_credentials

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role, settings=settings)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
