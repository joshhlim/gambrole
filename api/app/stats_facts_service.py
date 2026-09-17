"""Business logic behind GET /stats/facts.

One row per ended session, carrying counters rather than rates. The client
filters those rows (by date, by opponent, by last-N) and only then divides,
which is the whole point: a rate computed per session can't be re-averaged
correctly across an arbitrary selection, and the API round trip to Singapore
is slow enough (~0.7s) that recomputing server-side on every filter change
would make the page feel dead. All the game-specific interpretation stays in
the cores — this module only assembles.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from mahjong_core.models import MahjongSessionFacts
from mahjong_core.stats import mahjong_session_facts
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import Member, TaidiSessionFacts
from taidi_core.stats import taidi_session_facts

from .events_store import rebuild_mahjong_state_with_invite, rebuild_taidi_state_with_invite
from .money import MAHJONG_CHIP_VALUE_CENTS
from .stats_service import ended_room_refs


class OpponentRef(BaseModel):
    player_id: UUID
    display_name: str


class SessionFact(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    #: Always real cents, so Taidi and Mahjong sessions can be summed
    #: together on the overview (Mahjong plays in chips — see money.py).
    net_cents: int
    #: Everyone else at the table, for the "played with" filter and tallies.
    opponents: list[OpponentRef]
    taidi: TaidiSessionFacts | None = None
    mahjong: MahjongSessionFacts | None = None


class StatsFactsResponse(BaseModel):
    #: Oldest first — the client wants them in play order to draw a
    #: cumulative trend, and reversing a list is free.
    sessions: list[SessionFact]


async def build_facts_for(session: AsyncSession, player_id: UUID) -> StatsFactsResponse:
    room_refs = await ended_room_refs(session, player_id)
    facts: list[SessionFact] = []

    def _opponents(members: dict[UUID, Member]) -> list[OpponentRef]:
        return [
            OpponentRef(player_id=pid, display_name=m.display_name)
            for pid, m in members.items()
            if pid != player_id
        ]

    for room_id, game_type in room_refs:
        # ended_room_refs matches anyone who ever joined, including players
        # who ducked into the lobby and left before it started — they didn't
        # play this game. Same filter as history/stats.
        if game_type == "mahjong":
            mj_state, _invite = await rebuild_mahjong_state_with_invite(session, room_id)
            if player_id not in mj_state.members:
                continue
            assert mj_state.ended_at is not None  # ended_room_refs filters on status
            facts.append(
                SessionFact(
                    room_id=room_id,
                    game_type="mahjong",
                    ended_at=mj_state.ended_at,
                    net_cents=mj_state.balances.get(player_id, 0) * MAHJONG_CHIP_VALUE_CENTS,
                    opponents=_opponents(mj_state.members),
                    mahjong=mahjong_session_facts(mj_state, player_id),
                )
            )
        else:
            td_state, _invite = await rebuild_taidi_state_with_invite(session, room_id)
            if player_id not in td_state.members:
                continue
            assert td_state.ended_at is not None
            facts.append(
                SessionFact(
                    room_id=room_id,
                    game_type="taidi",
                    ended_at=td_state.ended_at,
                    net_cents=td_state.balances.get(player_id, 0),
                    opponents=_opponents(td_state.members),
                    taidi=taidi_session_facts(td_state, player_id),
                )
            )

    facts.sort(key=lambda f: f.ended_at)
    return StatsFactsResponse(sessions=facts)
