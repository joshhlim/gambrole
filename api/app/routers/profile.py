"""Profiles, photos, preferences and privacy — see profile_service.py."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..db import user_avatars as avatars_table
from ..db import users as users_table
from ..friends_service import relationship
from ..profile_service import (
    ACCENTS,
    MAX_AVATAR_BYTES,
    Preferences,
    StatsVisibility,
    Visibility,
    read_preferences,
    sniff_image,
    valid_avatar_signature,
)
from ..ratelimit import rate_limit
from ..stats_service import build_stats_for
from ..time import utcnow
from ..users_service import ensure_user, get_profile, profile_of, profiles_for

router = APIRouter(tags=["profile"])


class ProfileUpdate(BaseModel):
    """Empty strings clear a field."""

    bio: str | None = Field(default=None, max_length=160)
    city: str | None = Field(default=None, max_length=60)
    accent: str | None = Field(default=None, max_length=16)


class PreferencesUpdate(BaseModel):
    theme: Literal["system", "light", "dark"] | None = None
    onboarded: bool | None = None
    currency_symbol: str | None = Field(default=None, max_length=8)
    # Per game; null for a game clears its saved default.
    default_rules: dict[Literal["taidi", "mahjong"], dict[str, Any] | None] | None = None


class PrivacyUpdate(BaseModel):
    profile_visibility: Visibility | None = None
    stats_visibility: StatsVisibility | None = None
    searchable: bool | None = None


class ProfilesRequest(BaseModel):
    ids: list[UUID] = Field(max_length=50)


async def _my_profile(session: AsyncSession, user: CurrentUser) -> dict[str, Any]:
    profile = await get_profile(session, user.user_id)
    assert profile is not None  # every route here runs ensure_user first
    return profile.model_dump(mode="json")


@router.patch("/users/me/profile")
async def update_profile(
    body: ProfileUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    values: dict[str, Any] = {}
    for field in ("bio", "city"):
        raw = getattr(body, field)
        if raw is not None:
            values[field] = " ".join(raw.split()) or None
    if body.accent is not None:
        if body.accent and body.accent not in ACCENTS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown accent colour.")
        values["accent"] = body.accent or None
    if values:
        await session.execute(
            update(users_table)
            .where(users_table.c.user_id == user.user_id)
            .values(**values, updated_at=utcnow())
        )
        await session.commit()
    return await _my_profile(session, user)


@router.put("/users/me/avatar", dependencies=[Depends(rate_limit("avatar-upload", 20))])
async def put_avatar(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The raw image as the body. The client shrinks it to 256px first; the
    API only checks it's really an image and small enough."""
    data = await request.body()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That photo is too large.")
    content_type = sniff_image(data)
    if content_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use a JPEG, PNG or WebP image.")
    await ensure_user(session, user)
    now = utcnow()
    stmt = pg_insert(avatars_table).values(
        user_id=user.user_id, content_type=content_type, data=data, updated_at=now
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"content_type": content_type, "data": data, "updated_at": now},
        )
    )
    await session.execute(
        update(users_table)
        .where(users_table.c.user_id == user.user_id)
        .values(avatar_version=func.coalesce(users_table.c.avatar_version, 0) + 1, updated_at=now)
    )
    await session.commit()
    return await _my_profile(session, user)


@router.delete("/users/me/avatar")
async def delete_avatar(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    await session.execute(delete(avatars_table).where(avatars_table.c.user_id == user.user_id))
    await session.execute(
        update(users_table)
        .where(users_table.c.user_id == user.user_id)
        .values(avatar_version=None, updated_at=utcnow())
    )
    await session.commit()
    return await _my_profile(session, user)


@router.get("/avatars/{user_id}")
async def get_avatar(
    user_id: UUID, v: int, sig: str, session: AsyncSession = Depends(get_session)
) -> Response:
    """Public by design, but only reachable with a URL the API signed — see
    profile_service's module docstring."""
    if not valid_avatar_signature(user_id, v, sig):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    row = (
        await session.execute(select(avatars_table).where(avatars_table.c.user_id == user_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return Response(
        content=row.data,
        media_type=row.content_type,
        # The version is in the URL, so this exact URL never changes content.
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.put("/users/me/preferences")
async def put_preferences(
    body: PreferencesUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    row = (
        await session.execute(
            select(users_table.c.preferences).where(users_table.c.user_id == user.user_id)
        )
    ).first()
    current = read_preferences(row.preferences if row else None).model_dump(mode="json")
    if body.theme is not None:
        current["theme"] = body.theme
    if body.onboarded is not None:
        current["onboarded"] = body.onboarded
    if body.currency_symbol is not None:
        current["currency_symbol"] = body.currency_symbol
    if body.default_rules is not None:
        for game, rules in body.default_rules.items():
            if rules is None:
                current["default_rules"].pop(game, None)
            else:
                current["default_rules"][game] = rules
    try:
        merged = Preferences.model_validate(current)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    await session.execute(
        update(users_table)
        .where(users_table.c.user_id == user.user_id)
        .values(preferences=merged.model_dump(mode="json"), updated_at=utcnow())
    )
    await session.commit()
    return await _my_profile(session, user)


@router.put("/users/me/privacy")
async def put_privacy(
    body: PrivacyUpdate,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    values = body.model_dump(exclude_none=True)
    if values:
        await session.execute(
            update(users_table)
            .where(users_table.c.user_id == user.user_id)
            .values(**values, updated_at=utcnow())
        )
        await session.commit()
    return await _my_profile(session, user)


@router.post("/users/profiles")
async def bulk_profiles(
    body: ProfilesRequest,
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Names, photos and accents for a set of players — e.g. everyone at a
    table, fetched once rather than carried on every room poll. Guests and
    unknown ids are simply absent."""
    found = await profiles_for(session, body.ids)
    return {str(pid): p.model_dump(mode="json") for pid, p in found.items()}


async def _public_profile(session: AsyncSession, viewer: UUID, row: Any) -> dict[str, Any]:
    is_self = row.user_id == viewer
    friendship = "self" if is_self else await relationship(session, viewer, row.user_id)
    is_friend = friendship == "friends"

    details_visible = (
        is_self
        or row.profile_visibility == "everyone"
        or (row.profile_visibility == "friends" and is_friend)
    )
    stats_visible = is_self or (row.stats_visibility == "friends" and is_friend)

    headline: dict[str, Any] | None = None
    if stats_visible:
        overview = (await build_stats_for(session, row.user_id)).overview
        headline = {
            "total_sessions": overview.total_sessions,
            "total_cents": overview.total_cents,
            "favorite_game": overview.favorite_game,
            "current_streak": overview.current_streak,
            "last_played": overview.last_played.isoformat() if overview.last_played else None,
        }
    return {
        **profile_of(row).model_dump(mode="json"),
        "bio": row.bio if details_visible else None,
        "city": row.city if details_visible else None,
        "friendship": friendship,
        "stats": headline,
    }


@router.get("/users/{user_id}/profile")
async def public_profile(
    user_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = (
        await session.execute(select(users_table).where(users_table.c.user_id == user_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such player.")
    return await _public_profile(session, user.user_id, row)


@router.get("/users/by-username/{username}/profile")
async def public_profile_by_username(
    username: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    handle = username.strip().lstrip("@").lower()
    row = (
        await session.execute(select(users_table).where(users_table.c.username == handle))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such player.")
    return await _public_profile(session, user.user_id, row)
