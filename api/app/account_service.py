"""Deleting an account (App Store guideline 5.1.1(v): an app with sign-up
must let you delete your account from inside it).

What goes: everything that identifies the person — name, handle, email,
bio, city, photo, preferences, friendships, group memberships, and the
sign-in itself. What stays: the games they played. Those are other people's
records too (their results, their debts, their stats), so the games keep
their numbers and the deleted player becomes "Deleted player" in them.

That means one deliberate exception to ADR-0001's append-only event log:
the name in the deleted player's own `player_joined` events is overwritten.
Erasing personal data is the one reason to touch the log, and only the
display name changes — never a seat, a score, or an id — so every folded
state is the same game it was.

Refused while it would leave someone else stuck: mid-game (a live or lobby
room), or with a debt either way that isn't settled yet.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.request
from uuid import UUID

from sqlalchemy import cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import group_service
from .auth import remember_deleted
from .config import settings
from .db import events as events_table
from .db import friendships as friendships_table
from .db import group_members as group_members_table
from .db import guests as guests_table
from .db import rooms as rooms_table
from .db import settlements as settlements_table
from .db import test_accounts as test_accounts_table
from .db import user_avatars as avatars_table
from .db import users as users_table
from .events_store import find_active_room
from .identity import identity_ids
from .time import utcnow

DELETED_NAME = "Deleted player"


class AccountBlocked(Exception):
    """Deleting now would strand someone else; the message says what to do."""


class DeletionUnavailable(Exception):
    """The server can't remove the sign-in, so it won't delete anything."""


def _admin_headers(key: str) -> dict[str, str]:
    """A secret key (sb_secret_…) goes on `apikey` alone — it isn't a JWT,
    and Supabase rejects one sent as a Bearer token. A legacy service_role
    key is a JWT, and the admin API wants it on both."""
    headers = {"apikey": key}
    if not key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _delete_supabase_user(user_id: UUID) -> None:
    """Supabase's admin API: removes the sign-in and revokes its sessions."""
    assert settings.supabase_url and settings.supabase_service_role_key
    req = urllib.request.Request(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}",
        method="DELETE",
        headers=_admin_headers(settings.supabase_service_role_key),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            res.read()
    except urllib.error.HTTPError as e:
        # Already gone is as good as deleted (a retry after a lost reply).
        if e.code != 404:
            raise DeletionUnavailable(f"Couldn't remove the sign-in ({e.code}).") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise DeletionUnavailable("Couldn't reach the sign-in service — try again.") from e


async def delete_account(session: AsyncSession, user_id: UUID) -> None:
    if settings.auth_mode == "supabase" and not (
        settings.supabase_url and settings.supabase_service_role_key
    ):
        raise DeletionUnavailable("Account deletion isn't set up on the server yet.")

    if await find_active_room(session, user_id) is not None:
        raise AccountBlocked("Leave or finish your current game first.")

    ids = await identity_ids(session, user_id)
    open_debts = (
        await session.execute(
            select(func.count())
            .select_from(settlements_table)
            .where(
                or_(
                    settlements_table.c.from_player.in_(ids), settlements_table.c.to_player.in_(ids)
                ),
                settlements_table.c.status != "approved",
            )
        )
    ).scalar_one()
    if open_debts:
        raise AccountBlocked(
            f"Settle your {open_debts} open debt{'' if open_debts == 1 else 's'} first — "
            "the other side is still waiting on them."
        )

    # Everything below is one transaction, committed only once the sign-in
    # is gone too: either the whole account goes, or none of it does.
    groups = (
        await session.execute(
            select(group_members_table.c.group_id).where(group_members_table.c.user_id == user_id)
        )
    ).all()
    for g in groups:
        await group_service.leave_uncommitted(session, g.group_id, user_id)

    await session.execute(
        delete(friendships_table).where(
            or_(
                friendships_table.c.requester_id == user_id,
                friendships_table.c.addressee_id == user_id,
            )
        )
    )
    await session.execute(delete(avatars_table).where(avatars_table.c.user_id == user_id))
    await session.execute(
        delete(test_accounts_table).where(test_accounts_table.c.user_id == user_id)
    )

    # The name in past games: their own seats, the guest seats they claimed
    # (a host typed the person's name there), and rooms they hosted.
    await session.execute(
        update(events_table)
        .where(
            events_table.c.type == "player_joined",
            events_table.c.payload["player_id"].astext.in_([str(i) for i in ids]),
        )
        .values(
            payload=events_table.c.payload.op("||")(cast({"display_name": DELETED_NAME}, JSONB))
        )
    )
    await session.execute(
        update(guests_table)
        .where(guests_table.c.claimed_by == user_id)
        .values(display_name=DELETED_NAME)
    )
    await session.execute(
        update(rooms_table)
        .where(rooms_table.c.host_id == user_id)
        .values(host_display_name=DELETED_NAME)
    )

    # An upsert, not an update: someone can delete an account whose row was
    # never written (ensure_user runs on first use, not first sign-in), and
    # the deleted row is what stops a later request recreating one.
    now = utcnow()
    anonymous: dict[str, object] = {
        "display_name": DELETED_NAME,
        "username": None,
        "email": None,
        "bio": None,
        "city": None,
        "accent": None,
        "avatar_version": None,
        "preferences": {},
        "profile_visibility": "nobody",
        "stats_visibility": "nobody",
        "searchable": False,
        "deleted_at": now,
        "updated_at": now,
    }
    await session.execute(
        pg_insert(users_table)
        .values(user_id=user_id, created_at=now, **anonymous)
        .on_conflict_do_update(index_elements=["user_id"], set_=anonymous)
    )

    if settings.auth_mode == "supabase":
        await asyncio.to_thread(_delete_supabase_user, user_id)
    await session.commit()
    remember_deleted(user_id)
