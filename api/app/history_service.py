"""Business logic behind GET /history/me.

Deliberately separate from stats_service.build_stats_for: that endpoint's
`SessionResult` trend is sorted ascending for a chart's running
`cumulative_cents` total, while history wants most-recent-first plus
settlement-status detail the chart has no use for.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from mahjong_core.models import RoomState as MahjongRoomState
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import RoomState as TaidiRoomState

from .db import settlements as settlements_table
from .events_store import rebuild_mahjong_state_with_invite, rebuild_taidi_state_with_invite
from .money import MAHJONG_CHIP_VALUE_CENTS
from .stats_service import ended_room_refs


class HistoryEntry(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    net_cents: int
    settlements_total: int
    settlements_pending: int
    settlements_needs_my_approval: int
    all_settled: bool


class HistoryResponse(BaseModel):
    games: list[HistoryEntry]  # most-recent-first


async def build_history_for(session: AsyncSession, player_id: UUID) -> HistoryResponse:
    room_refs = await ended_room_refs(session, player_id)
    if not room_refs:
        return HistoryResponse(games=[])

    room_ids = [room_id for room_id, _game_type in room_refs]
    settlement_rows = (
        await session.execute(
            select(settlements_table).where(settlements_table.c.room_id.in_(room_ids))
        )
    ).all()
    by_room: dict[UUID, list] = {}
    for row in settlement_rows:
        by_room.setdefault(row.room_id, []).append(row)

    entries: list[HistoryEntry] = []
    for room_id, game_type in room_refs:
        state: TaidiRoomState | MahjongRoomState
        if game_type == "mahjong":
            state, _invite_code = await rebuild_mahjong_state_with_invite(session, room_id)
            net_cents = state.balances.get(player_id, 0) * MAHJONG_CHIP_VALUE_CENTS
        else:
            state, _invite_code = await rebuild_taidi_state_with_invite(session, room_id)
            net_cents = state.balances.get(player_id, 0)

        rows = by_room.get(room_id, [])
        pending = sum(1 for r in rows if r.status in ("pending", "marked_paid"))
        needs_my_approval = sum(
            1 for r in rows if r.status == "marked_paid" and r.to_player == player_id
        )
        assert state.ended_at is not None  # guaranteed by ended_room_refs' status='ended' filter
        entries.append(
            HistoryEntry(
                room_id=room_id,
                game_type=game_type,
                ended_at=state.ended_at,
                net_cents=net_cents,
                settlements_total=len(rows),
                settlements_pending=pending,
                settlements_needs_my_approval=needs_my_approval,
                all_settled=pending == 0,
            )
        )

    entries.sort(key=lambda e: e.ended_at, reverse=True)
    return HistoryResponse(games=entries)
