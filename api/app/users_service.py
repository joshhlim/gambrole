"""The user directory: who exists, what they're called, how to find them.

Until now the app had no notion of a user outside a room — identity was
whatever the JWT said, and a player only became visible by acting in a game
(see ADR-0007). Friends need the opposite: a durable record you can look up
before you've ever played together.

Rows are mirrored from JWT claims rather than read live from Supabase's
`auth.users`, because local dev and the whole test suite run on a plain
Postgres with no `auth` schema, and because nothing else in the app depends
on Supabase's internal column shapes. scripts/backfill_users.py seeds the
table from `auth.users` once so the directory is complete on day one.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .db import users as users_table
from .time import utcnow

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,24}$")
USERNAME_HELP = "3-24 characters, letters, numbers and underscores only."


class UserProfile(BaseModel):
    """What one player may know about another. Note the absence of email:
    it's searchable but never disclosed."""

    user_id: UUID
    display_name: str
    username: str | None


class MyProfile(UserProfile):
    email: str | None  # your own address, so Settings can show what's on file


class InvalidUsername(Exception):
    pass


class UsernameTaken(Exception):
    pass


async def ensure_user(session: AsyncSession, user: CurrentUser) -> None:
    """Record (or refresh) the caller in the directory.

    Called from the handful of endpoints everyone hits anyway rather than
    from get_current_user, because the database is a long way from the API
    (~110ms per statement) and taxing every single request to keep a display
    name fresh isn't worth it.
    """
    now = utcnow()
    stmt = pg_insert(users_table).values(
        user_id=user.user_id,
        email=user.email,
        display_name=user.display_name,
        created_at=now,
        updated_at=now,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "display_name": stmt.excluded.display_name,
                "updated_at": stmt.excluded.updated_at,
                # Never overwrite a stored address with NULL: dev tokens carry
                # none, and a backfilled row shouldn't lose its email just
                # because someone signed in through a different mode.
                "email": func.coalesce(stmt.excluded.email, users_table.c.email),
            },
        )
    )
    await session.commit()


async def get_profile(session: AsyncSession, user_id: UUID) -> MyProfile | None:
    row = (
        await session.execute(select(users_table).where(users_table.c.user_id == user_id))
    ).first()
    if row is None:
        return None
    return MyProfile(
        user_id=row.user_id,
        display_name=row.display_name,
        username=row.username,
        email=row.email,
    )


async def profiles_for(session: AsyncSession, user_ids: list[UUID]) -> dict[UUID, UserProfile]:
    """Bulk name lookup — one query instead of one per friend."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(select(users_table).where(users_table.c.user_id.in_(user_ids)))
    ).all()
    return {
        r.user_id: UserProfile(user_id=r.user_id, display_name=r.display_name, username=r.username)
        for r in rows
    }


async def set_username(session: AsyncSession, user_id: UUID, raw: str) -> str:
    """Claim or change a username. Case is not meaningful — stored folded so
    "@Josh" and "@josh" can't be two people."""
    username = raw.strip().lstrip("@").lower()
    if not USERNAME_RE.match(username):
        raise InvalidUsername(USERNAME_HELP)

    taken = (
        await session.execute(
            select(users_table.c.user_id).where(
                users_table.c.username == username, users_table.c.user_id != user_id
            )
        )
    ).first()
    if taken is not None:
        raise UsernameTaken(f"@{username} is already taken.")

    await session.execute(
        users_table.update()
        .where(users_table.c.user_id == user_id)
        .values(username=username, updated_at=utcnow())
    )
    await session.commit()
    return username


async def search(session: AsyncSession, query: str, *, exclude: UUID) -> list[UserProfile]:
    """Find someone by their exact address or username.

    Exact match only, and never a prefix or fuzzy search: a directory you can
    browse is a directory you can scrape. You can find someone you already
    know how to contact, and nothing more.
    """
    q = query.strip().lower().lstrip("@")
    if not q:
        return []
    rows = (
        await session.execute(
            select(users_table).where(
                or_(users_table.c.email == q, users_table.c.username == q),
                users_table.c.user_id != exclude,
            )
        )
    ).all()
    return [
        UserProfile(user_id=r.user_id, display_name=r.display_name, username=r.username)
        for r in rows
    ]
