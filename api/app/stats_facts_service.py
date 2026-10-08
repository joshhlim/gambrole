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
from mahjong_core.models import RoomState as MahjongRoomState
from mahjong_core.stats import mahjong_session_facts
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.models import Member, TaidiSessionFacts
from taidi_core.stats import taidi_session_facts

from .stats_service import load_ended_rooms
from .users_service import UserProfile, profiles_for


class OpponentRef(BaseModel):
    player_id: UUID
    display_name: str


class SessionFact(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    #: Real cents for both games, so sessions can be summed together.
    net_cents: int
    #: Everyone else at the table, for the "played with" filter and tallies.
    opponents: list[OpponentRef]
    taidi: TaidiSessionFacts | None = None
    mahjong: MahjongSessionFacts | None = None


class StatsFactsResponse(BaseModel):
    #: Whose stats these are, so a page showing a friend's can say so (and
    #: a deep link doesn't have to look the name up separately). None only
    #: if the player has somehow never been recorded in the directory.
    player: UserProfile | None
    #: Oldest first — the client wants them in play order to draw a
    #: cumulative trend, and reversing a list is free.
    sessions: list[SessionFact]


async def build_facts_for(session: AsyncSession, player_id: UUID) -> StatsFactsResponse:
    _ids, room_refs, states = await load_ended_rooms(session, player_id)
    facts: list[SessionFact] = []

    def _opponents(members: dict[UUID, Member]) -> list[OpponentRef]:
        return [
            OpponentRef(player_id=pid, display_name=m.display_name)
            for pid, m in members.items()
            if pid != player_id
        ]

    for room_id, _game_type in room_refs:
        # A balance is the test of having played — see history_service for
        # why membership isn't (someone who stepped out mid-game keeps the
        # former but not the latter).
        state = states[room_id]
        if player_id not in state.balances:
            continue
        if isinstance(state, MahjongRoomState):
            mj_state = state
            assert mj_state.ended_at is not None  # ended_room_refs filters on status
            facts.append(
                SessionFact(
                    room_id=room_id,
                    game_type="mahjong",
                    ended_at=mj_state.ended_at,
                    net_cents=mj_state.balances.get(player_id, 0),
                    opponents=_opponents(mj_state.members),
                    mahjong=mahjong_session_facts(mj_state, player_id),
                )
            )
        else:
            td_state = state
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
    profile = (await profiles_for(session, [player_id])).get(player_id)
    return StatsFactsResponse(player=profile, sessions=facts)
