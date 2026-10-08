"""Who a player is, across the guests they've claimed.

A guest (db.guests) plays under its own id. When someone claims a guest's
games for their account, that id becomes one of the account's identities:
queries over a player's history match any of them, and folded room states
have the claimed guest ids rewritten to the account id before anything
downstream looks at them — so stats, history and debts code keeps asking
"is `player_id` in this room" and gets the right answer. The event log
itself is never touched (ADR-0001: append-only).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import guests as guests_table


async def identity_ids(session: AsyncSession, user_id: UUID) -> list[UUID]:
    """The account itself first, then every guest it has claimed."""
    rows = (
        await session.execute(
            select(guests_table.c.guest_id).where(guests_table.c.claimed_by == user_id)
        )
    ).all()
    return [user_id, *(row.guest_id for row in rows)]


def remap[S: BaseModel](state: S, ids: list[UUID]) -> S:
    """`state` with every claimed guest id (ids[1:]) replaced by the account
    id (ids[0]). Done on the serialised form: UUIDs are unique strings, so a
    textual replace reaches every place an id can appear (balances, members,
    transfers, rounds, hands) without a per-game walker to keep in sync. A
    user can't claim a guest from a game they also played (claim refuses
    it), so no two ids in one room ever collapse into one."""
    if len(ids) < 2:
        return state
    raw = state.model_dump_json()
    for alias in ids[1:]:
        raw = raw.replace(str(alias), str(ids[0]))
    return type(state).model_validate_json(raw)
