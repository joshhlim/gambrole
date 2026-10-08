"""Claiming a guest's games for a real account.

A guest (see db.guests) is someone the host seated without an account. Once
the game is over, the host can share that guest's claim link; opening it
shows what's being claimed, and claiming makes the guest one of the
account's identities (identity.py) — their games, stats and debts appear as
the account's from then on.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import RoomStatus

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..db import guests as guests_table
from ..events_store import load_room
from ..identity import identity_ids
from ..ratelimit import rate_limit
from ..time import utcnow
from ..users_service import ensure_user

router = APIRouter(prefix="/guests", tags=["guests"])


async def _claim_row(session: AsyncSession, token: str) -> Any:
    row = (
        await session.execute(select(guests_table).where(guests_table.c.claim_token == token))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is missing or already used.")
    return row


@router.get("/claim/{token}", dependencies=[Depends(rate_limit("guest-claim", 30))])
async def preview_claim(token: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """What a claim link would claim. No sign-in needed: it's shown before
    the guest has an account. The token itself is the secret."""
    row = await _claim_row(session, token)
    state, meta = await load_room(session, row.room_id)
    host = state.members.get(state.host_id)
    return {
        "display_name": row.display_name,
        "game_type": meta.game_type,
        "status": state.status.value,
        "ended_at": state.ended_at.isoformat() if state.ended_at else None,
        "net_cents": state.balances.get(row.guest_id, 0),
        "host_display_name": host.display_name if host else None,
        "claimed": row.claimed_by is not None,
    }


@router.post("/claim/{token}", dependencies=[Depends(rate_limit("guest-claim", 30))])
async def claim(
    token: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await _claim_row(session, token)
    if row.claimed_by is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This guest has already been claimed.")
    state, meta = await load_room(session, row.room_id)
    # Claiming mid-game would give one person two seats at a live table.
    if state.status != RoomStatus.ENDED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This game hasn't finished yet — claim it once it ends."
        )
    # One person, one seat: someone who also played this game as themselves
    # (or as another guest they've claimed) can't take a second seat in it.
    ids = await identity_ids(session, user.user_id)
    if any(pid in state.balances or pid == state.host_id for pid in ids):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already played in this game, so you can't claim a guest in it.",
        )
    await ensure_user(session, user)
    result = await session.execute(
        update(guests_table)
        .where(guests_table.c.guest_id == row.guest_id, guests_table.c.claimed_by.is_(None))
        .values(claimed_by=user.user_id, claimed_at=utcnow())
    )
    await session.commit()
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_409_CONFLICT, "This guest has already been claimed.")
    return {"room_id": str(row.room_id), "game_type": meta.game_type}
