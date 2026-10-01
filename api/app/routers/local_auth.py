"""Email + password accounts without Supabase (TAIDI_AUTH_MODE=local).

For internal testing. Accounts live in the `test_accounts` table exactly as
entered — passwords and reset tokens in plain text — so the whole thing can
be read in a SQL client or the Supabase Table Editor. They're unrelated to
Supabase accounts: switching modes means a separate set of players.

The web app's sign-in, sign-up, forgot-password and Settings screens are the
same in both modes; web/src/lib/auth.ts routes them here instead of to
Supabase. Error messages mirror Supabase's wording so the screens read the
same. There's no email in this mode, so a password reset link is written to
the API log (and the token is visible in the table) instead of being sent.

Every endpoint 404s unless the API is running in local mode.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import MAX_DISPLAY_NAME, CurrentUser, get_current_user, mint_local_token
from ..config import settings
from ..db import get_session
from ..db import test_accounts as accounts_table
from ..ratelimit import rate_limit
from ..time import utcnow
from ..users_service import ensure_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/local", tags=["auth"])

MIN_PASSWORD = 6  # Supabase's default, which the web forms already enforce
RESET_TTL = timedelta(hours=1)


def _require_local_mode() -> None:
    if settings.auth_mode != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


Email = Field(min_length=3, max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\s*$")
Password = Field(max_length=128)


class SignupRequest(BaseModel):
    email: str = Email
    password: str = Password
    display_name: str = Field(max_length=MAX_DISPLAY_NAME)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Password


class ResetRequest(BaseModel):
    email: str = Field(max_length=320)
    # Where the link should land — the web app's /auth/callback, as Supabase
    # takes it. Only honoured for an origin the API already trusts.
    redirect_to: str | None = Field(default=None, max_length=512)


class ResetConfirmRequest(BaseModel):
    token: str = Field(max_length=64)
    password: str = Password


class UpdateAccountRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=MAX_DISPLAY_NAME)
    email: str | None = Field(
        default=None, min_length=3, max_length=320, pattern=r"^\s*[^@\s]+@[^@\s]+\s*$"
    )
    password: str | None = Field(default=None, max_length=128)


class SessionResponse(BaseModel):
    access_token: str
    user_id: str
    display_name: str
    email: str


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password should be at least {MIN_PASSWORD} characters.",
        )


async def _session_for(session: AsyncSession, row: Any) -> SessionResponse:
    """A token for `row`, after bringing the app's user directory in line
    with it (the same thing any signed-in request does on first use)."""
    await ensure_user(
        session,
        CurrentUser(user_id=row.user_id, display_name=row.display_name, email=row.email),
    )
    return SessionResponse(
        access_token=mint_local_token(row.user_id, row.display_name, row.email),
        user_id=str(row.user_id),
        display_name=row.display_name,
        email=row.email,
    )


async def _account(session: AsyncSession, user_id: UUID) -> Any:
    return (
        await session.execute(select(accounts_table).where(accounts_table.c.user_id == user_id))
    ).first()


@router.post(
    "/signup",
    response_model=SessionResponse,
    dependencies=[Depends(_require_local_mode), Depends(rate_limit("local-signup", 10))],
)
async def signup(
    body: SignupRequest, session: AsyncSession = Depends(get_session)
) -> SessionResponse:
    _check_password(body.password)
    now = utcnow()
    user_id = uuid4()
    values = {
        "user_id": user_id,
        "email": _normalise_email(body.email),
        "password": body.password,
        "display_name": " ".join(body.display_name.split()) or "Player",
        "created_at": now,
        "updated_at": now,
    }
    try:
        await session.execute(accounts_table.insert().values(**values))
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User already registered") from e
    row = await _account(session, user_id)
    return await _session_for(session, row)


@router.post(
    "/login",
    response_model=SessionResponse,
    dependencies=[Depends(_require_local_mode), Depends(rate_limit("local-login", 20))],
)
async def login(
    body: LoginRequest, session: AsyncSession = Depends(get_session)
) -> SessionResponse:
    row = (
        await session.execute(
            select(accounts_table).where(accounts_table.c.email == _normalise_email(body.email))
        )
    ).first()
    if row is None or not secrets.compare_digest(row.password, body.password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid login credentials")
    return await _session_for(session, row)


@router.post(
    "/password-reset",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_local_mode), Depends(rate_limit("local-reset", 10))],
)
async def request_password_reset(
    body: ResetRequest, session: AsyncSession = Depends(get_session)
) -> None:
    """Always 204, like Supabase — whether an address has an account isn't
    something to answer to anyone who asks. If it does, the link is logged
    and its token is left in the table for whoever reads it."""
    email = _normalise_email(body.email)
    row = (
        await session.execute(select(accounts_table).where(accounts_table.c.email == email))
    ).first()
    if row is None:
        return
    token = secrets.token_urlsafe(32)
    await session.execute(
        accounts_table.update()
        .where(accounts_table.c.user_id == row.user_id)
        .values(reset_token=token, reset_expires_at=utcnow() + RESET_TTL, updated_at=utcnow())
    )
    await session.commit()
    base = body.redirect_to or ""
    if not any(base.startswith(origin) for origin in settings.cors_origins):
        base = f"{settings.cors_origins[0]}/auth/callback"
    logger.warning("Local-mode password reset link for %s: %s?reset_token=%s", email, base, token)


@router.post(
    "/password-reset/confirm",
    response_model=SessionResponse,
    dependencies=[Depends(_require_local_mode), Depends(rate_limit("local-reset", 10))],
)
async def confirm_password_reset(
    body: ResetConfirmRequest, session: AsyncSession = Depends(get_session)
) -> SessionResponse:
    """Sets the new password and signs you in, the way following a Supabase
    recovery link leaves you signed in."""
    _check_password(body.password)
    row = (
        await session.execute(
            select(accounts_table).where(accounts_table.c.reset_token == body.token)
        )
    ).first()
    if row is None or row.reset_expires_at is None or row.reset_expires_at < utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is missing or already used.")
    await session.execute(
        accounts_table.update()
        .where(accounts_table.c.user_id == row.user_id)
        .values(
            password=body.password, reset_token=None, reset_expires_at=None, updated_at=utcnow()
        )
    )
    await session.commit()
    return await _session_for(session, await _account(session, row.user_id))


@router.patch(
    "/me",
    response_model=SessionResponse,
    dependencies=[Depends(_require_local_mode)],
)
async def update_account(
    body: UpdateAccountRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Settings' name / email / password changes. Returns a fresh token,
    since the old one still carries the old name and address."""
    row = await _account(session, user.user_id)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No such account.")
    values: dict[str, Any] = {}
    if body.display_name is not None:
        values["display_name"] = " ".join(body.display_name.split()) or "Player"
    if body.email is not None:
        values["email"] = _normalise_email(body.email)
    if body.password is not None:
        _check_password(body.password)
        values["password"] = body.password
    if values:
        try:
            await session.execute(
                accounts_table.update()
                .where(accounts_table.c.user_id == user.user_id)
                .values(**values, updated_at=utcnow())
            )
            await session.commit()
        except IntegrityError as e:
            await session.rollback()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A user with this email address has already been registered",
            ) from e
    return await _session_for(session, await _account(session, user.user_id))
