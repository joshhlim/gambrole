"""Business logic behind GET /stats/me.

Finds every ENDED room a player has history in (via the read-model from
ADR-0007: rooms.status/.ended_at and room_participants), rebuilds each one,
and feeds the results to taidi_core's/mahjong_core's stats aggregators —
all in one pass, so the frontend's overview/Taidi/Mahjong tabs come from a
single request instead of three redundant ones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from mahjong_core.models import MahjongPlayerStats
from mahjong_core.models import RoomState as MahjongRoomState
from mahjong_core.stats import mahjong_hand_stats
from pydantic import BaseModel
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import RoomState as TaidiRoomState
from taidi_core.models import TaidiPlayerStats
from taidi_core.stats import taidi_round_stats

from .db import room_participants as room_participants_table
from .db import rooms as rooms_table
from .events_store import rebuild_mahjong_state_with_invite, rebuild_taidi_state_with_invite
from .money import MAHJONG_CHIP_VALUE_CENTS


class SessionResult(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    net_cents: int
    cumulative_cents: int


class OverviewStats(BaseModel):
    total_cents: int
    taidi_cents: int
    mahjong_cents: int
    mahjong_chips: int
    total_sessions: int
    taidi_sessions: int
    mahjong_sessions: int
    # Sign is direction (+ = win streak, - = loss streak), magnitude is the
    # count of consecutive same-sign sessions ending at the most recent
    # one; 0 if the most recent session was a tie or there are no sessions.
    current_streak: int
    favorite_game: Literal["taidi", "mahjong", "tied"] | None
    last_played: datetime | None
    trend: list[SessionResult]


class StatsResponse(BaseModel):
    overview: OverviewStats
    taidi: TaidiPlayerStats | None
    mahjong: MahjongPlayerStats | None


async def ended_room_refs(session: AsyncSession, player_id: UUID) -> list[tuple[UUID, str]]:
    """Every (room_id, game_type) for an ENDED room this player has history
    in — as host (rooms.host_id, who never gets a room_participants row —
    see ADR-0007) or as a joiner (room_participants)."""
    as_host = select(rooms_table.c.room_id, rooms_table.c.game_type).where(
        rooms_table.c.host_id == player_id, rooms_table.c.status == "ended"
    )
    as_participant = (
        select(rooms_table.c.room_id, rooms_table.c.game_type)
        .select_from(
            room_participants_table.join(
                rooms_table, room_participants_table.c.room_id == rooms_table.c.room_id
            )
        )
        .where(
            room_participants_table.c.player_id == player_id,
            rooms_table.c.status == "ended",
        )
    )
    rows = await session.execute(union(as_host, as_participant))
    return [(row.room_id, row.game_type) for row in rows.all()]


def _streak(sessions: list[SessionResult]) -> int:
    streak = 0
    for s in reversed(sessions):
        sign = 1 if s.net_cents > 0 else (-1 if s.net_cents < 0 else 0)
        if sign == 0:
            break
        if streak == 0:
            streak = sign
        elif (streak > 0) == (sign > 0):
            streak += sign
        else:
            break
    return streak


async def build_stats_for(session: AsyncSession, player_id: UUID) -> StatsResponse:
    room_refs = await ended_room_refs(session, player_id)

    taidi_rooms: list[TaidiRoomState] = []
    mahjong_rooms: list[MahjongRoomState] = []
    for room_id, game_type in room_refs:
        # ended_room_refs matches anyone room_participants has ever seen in
        # the room, which includes people who joined the lobby and left
        # before the game started. They didn't play it, so it shouldn't
        # count toward their sessions, streak or trend — and since leaving
        # mid-game is impossible, final membership is exactly "played it".
        if game_type == "mahjong":
            mahjong_state, _invite_code = await rebuild_mahjong_state_with_invite(session, room_id)
            if player_id in mahjong_state.members:
                mahjong_rooms.append(mahjong_state)
        else:
            taidi_state, _invite_code = await rebuild_taidi_state_with_invite(session, room_id)
            if player_id in taidi_state.members:
                taidi_rooms.append(taidi_state)

    taidi_stats = taidi_round_stats(taidi_rooms).get(player_id)
    mahjong_stats = mahjong_hand_stats(mahjong_rooms).get(player_id)

    sessions: list[SessionResult] = []
    for state in taidi_rooms:
        assert state.ended_at is not None  # guaranteed by the status='ended' filter
        sessions.append(
            SessionResult(
                room_id=state.room_id,
                game_type="taidi",
                ended_at=state.ended_at,
                net_cents=state.balances.get(player_id, 0),
                cumulative_cents=0,
            )
        )
    mahjong_chips_total = 0
    for mahjong_state in mahjong_rooms:
        assert mahjong_state.ended_at is not None
        chips = mahjong_state.balances.get(player_id, 0)
        mahjong_chips_total += chips
        sessions.append(
            SessionResult(
                room_id=mahjong_state.room_id,
                game_type="mahjong",
                ended_at=mahjong_state.ended_at,
                net_cents=chips * MAHJONG_CHIP_VALUE_CENTS,
                cumulative_cents=0,
            )
        )

    sessions.sort(key=lambda s: s.ended_at)
    running = 0
    for s in sessions:
        running += s.net_cents
        s.cumulative_cents = running

    taidi_cents = sum(s.net_cents for s in sessions if s.game_type == "taidi")
    mahjong_cents = sum(s.net_cents for s in sessions if s.game_type == "mahjong")
    taidi_sessions = len(taidi_rooms)
    mahjong_sessions = len(mahjong_rooms)

    favorite_game: Literal["taidi", "mahjong", "tied"] | None
    if taidi_sessions == 0 and mahjong_sessions == 0:
        favorite_game = None
    elif taidi_sessions == mahjong_sessions:
        favorite_game = "tied"
    else:
        favorite_game = "taidi" if taidi_sessions > mahjong_sessions else "mahjong"

    overview = OverviewStats(
        total_cents=taidi_cents + mahjong_cents,
        taidi_cents=taidi_cents,
        mahjong_cents=mahjong_cents,
        mahjong_chips=mahjong_chips_total,
        total_sessions=taidi_sessions + mahjong_sessions,
        taidi_sessions=taidi_sessions,
        mahjong_sessions=mahjong_sessions,
        current_streak=_streak(sessions),
        favorite_game=favorite_game,
        last_played=sessions[-1].ended_at if sessions else None,
        trend=sessions,
    )
    return StatsResponse(overview=overview, taidi=taidi_stats, mahjong=mahjong_stats)
