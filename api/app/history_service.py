"""Business logic behind GET /history/me.

Deliberately separate from stats_service.build_stats_for: that endpoint's
`SessionResult` trend is sorted ascending for a chart's running
`cumulative_cents` total, while history wants most-recent-first plus
settlement-status detail the chart has no use for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from mahjong_core.models import RoomState as MahjongRoomState
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import RoomState as TaidiRoomState

from .db import events as events_table
from .db import settlements as settlements_table
from .events_store import rebuild_mahjong_state_with_invite, rebuild_taidi_state_with_invite
from .money import MAHJONG_CHIP_VALUE_CENTS
from .stats_service import ended_room_refs


class HistoryEntry(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    net_cents: int
    # Counts cover only debts THIS player is party to — the row is their
    # history, and a game's other pairs aren't their business.
    settlements_total: int
    settlements_pending: int
    settlements_needs_my_approval: int
    all_settled: bool
    # Who ended the game, or None when the inactivity backstop did it (in
    # which case auto_ended is True). A game that ends by itself can mint
    # real debts, so it has to be possible to tell the two apart.
    ended_by: str | None
    auto_ended: bool


class HistoryResponse(BaseModel):
    games: list[HistoryEntry]  # most-recent-first


async def build_history_for(session: AsyncSession, player_id: UUID) -> HistoryResponse:
    room_refs = await ended_room_refs(session, player_id)
    if not room_refs:
        return HistoryResponse(games=[])

    room_ids = [room_id for room_id, _game_type in room_refs]
    # Only this player's own debts — see HistoryEntry's comment.
    settlement_rows = (
        await session.execute(
            select(settlements_table).where(
                settlements_table.c.room_id.in_(room_ids),
                or_(
                    settlements_table.c.from_player == player_id,
                    settlements_table.c.to_player == player_id,
                ),
            )
        )
    ).all()
    by_room: dict[UUID, list[Any]] = {}
    for row in settlement_rows:
        by_room.setdefault(row.room_id, []).append(row)

    # One query for every room's game_ended event, to recover who ended it
    # (the actor) and whether the backstop did it (payload reason).
    end_rows = (
        await session.execute(
            select(events_table.c.room_id, events_table.c.actor, events_table.c.payload).where(
                events_table.c.room_id.in_(room_ids),
                events_table.c.type == "game_ended",
            )
        )
    ).all()
    end_by_room = {row.room_id: row for row in end_rows}

    entries: list[HistoryEntry] = []
    for room_id, game_type in room_refs:
        state: TaidiRoomState | MahjongRoomState
        if game_type == "mahjong":
            state, _invite_code = await rebuild_mahjong_state_with_invite(session, room_id)
            net_cents = state.balances.get(player_id, 0) * MAHJONG_CHIP_VALUE_CENTS
        else:
            state, _invite_code = await rebuild_taidi_state_with_invite(session, room_id)
            net_cents = state.balances.get(player_id, 0)

        # room_participants remembers everyone who EVER joined (ADR-0007),
        # so it also matches people who ducked into the lobby and left
        # before the game began. They didn't play it — leaving mid-game is
        # impossible, so final membership is exactly "actually played".
        if player_id not in state.members:
            continue

        rows = by_room.get(room_id, [])
        pending = sum(1 for r in rows if r.status in ("pending", "marked_paid"))
        needs_my_approval = sum(
            1 for r in rows if r.status == "marked_paid" and r.to_player == player_id
        )
        end_row = end_by_room.get(room_id)
        auto_ended = bool(end_row is not None and (end_row.payload or {}).get("reason") == "stale")
        ended_by: str | None = None
        if end_row is not None and not auto_ended and end_row.actor is not None:
            member = state.members.get(end_row.actor)
            ended_by = member.display_name if member else None

        assert state.ended_at is not None  # guaranteed by ended_room_refs' status='ended' filter
        entries.append(
            HistoryEntry(
                room_id=room_id,
                game_type=cast(Literal["taidi", "mahjong"], game_type),
                ended_at=state.ended_at,
                net_cents=net_cents,
                settlements_total=len(rows),
                settlements_pending=pending,
                settlements_needs_my_approval=needs_my_approval,
                all_settled=pending == 0,
                ended_by=ended_by,
                auto_ended=auto_ended,
            )
        )

    entries.sort(key=lambda e: e.ended_at, reverse=True)
    return HistoryResponse(games=entries)
