"""Persistence for rooms and their event logs, and the fold that turns them
back into a RoomState — either taidi_core's or mahjong_core's, depending on
the room's stored game_type (see ADR-0006).

The generic endpoints (create, get-state, by-code) work with either type via
AnyRoomState. Each game's router narrows to its own concrete type via
rebuild_taidi_state_with_invite / rebuild_mahjong_state_with_invite, which
raise WrongGameType for a mismatch — e.g. calling a Mahjong action endpoint
against a room created as Taidi.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from uuid import uuid4

from mahjong_core import machine as mahjong_machine
from mahjong_core.models import Event as MahjongEvent
from mahjong_core.models import EventType as MahjongEventType
from mahjong_core.models import RoomState as MahjongRoomState
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core import machine as taidi_machine
from taidi_core.models import Event as TaidiEvent
from taidi_core.models import EventType as TaidiEventType
from taidi_core.models import RoomState as TaidiRoomState
from taidi_core.settlement import minimize_transfers

from .db import events as events_table
from .db import room_participants as room_participants_table
from .db import rooms as rooms_table
from .db import settlements as settlements_table
from .money import MAHJONG_CHIP_VALUE_CENTS

AnyRoomState = TaidiRoomState | MahjongRoomState

_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — easy to read aloud


def generate_invite_code(length: int = 6) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))


class RoomNotFound(Exception):
    pass


class WrongGameType(Exception):
    """Raised when an endpoint scoped to one game (taidi/mahjong) is called
    against a room created as the other."""

    def __init__(self, actual: str, expected: str):
        self.actual = actual
        self.expected = expected
        super().__init__(f"This room is a {actual} room, not {expected}.")


async def create_room(
    session: AsyncSession,
    *,
    room_id: UUID,
    host_id: UUID,
    host_display_name: str,
    now: datetime,
    game_type: str = "taidi",
) -> tuple[AnyRoomState, str, str]:
    invite_code = generate_invite_code()
    await session.execute(
        insert(rooms_table).values(
            room_id=room_id,
            invite_code=invite_code,
            host_id=host_id,
            host_display_name=host_display_name,
            created_at=now,
            game_type=game_type,
        )
    )
    await session.commit()
    if game_type == "mahjong":
        mahjong_state = MahjongRoomState.new(
            room_id=room_id, host_id=host_id, host_display_name=host_display_name, now=now
        )
        return mahjong_state, invite_code, game_type
    taidi_state = TaidiRoomState.new(
        room_id=room_id, host_id=host_id, host_display_name=host_display_name, now=now
    )
    return taidi_state, invite_code, game_type


async def resolve_invite_code(session: AsyncSession, invite_code: str) -> UUID | None:
    row = (
        await session.execute(
            select(rooms_table.c.room_id).where(rooms_table.c.invite_code == invite_code.upper())
        )
    ).first()
    return row.room_id if row else None


async def _load_room_seed(session: AsyncSession, room_id: UUID) -> Any:
    row = (
        await session.execute(select(rooms_table).where(rooms_table.c.room_id == room_id))
    ).first()
    if row is None:
        raise RoomNotFound(room_id)
    return row


async def _load_taidi_events(session: AsyncSession, room_id: UUID) -> list[TaidiEvent]:
    rows = await session.execute(
        select(events_table).where(events_table.c.room_id == room_id).order_by(events_table.c.seq)
    )
    return [
        TaidiEvent(
            event_id=r.id,
            room_id=r.room_id,
            seq=r.seq,
            type=TaidiEventType(r.type),
            actor=r.actor,
            payload=r.payload,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def _load_mahjong_events(session: AsyncSession, room_id: UUID) -> list[MahjongEvent]:
    rows = await session.execute(
        select(events_table).where(events_table.c.room_id == room_id).order_by(events_table.c.seq)
    )
    return [
        MahjongEvent(
            event_id=r.id,
            room_id=r.room_id,
            seq=r.seq,
            type=MahjongEventType(r.type),
            actor=r.actor,
            payload=r.payload,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def rebuild_state(session: AsyncSession, room_id: UUID) -> AnyRoomState:
    state, _invite_code, _game_type = await rebuild_state_with_invite(session, room_id)
    return state


async def rebuild_state_with_invite(
    session: AsyncSession, room_id: UUID
) -> tuple[AnyRoomState, str, str]:
    """Rebuilds whichever RoomState type matches the room's stored
    game_type. Generic endpoints (get-state, create) use this directly;
    each game's router narrows via rebuild_taidi_state_with_invite /
    rebuild_mahjong_state_with_invite instead."""
    seed = await _load_room_seed(session, room_id)
    if seed.game_type == "mahjong":
        mahjong_state = MahjongRoomState.new(
            room_id=seed.room_id,
            host_id=seed.host_id,
            host_display_name=seed.host_display_name,
            now=seed.created_at,
        )
        mahjong_state = mahjong_machine.fold(
            mahjong_state, await _load_mahjong_events(session, room_id)
        )
        return mahjong_state, seed.invite_code, seed.game_type

    taidi_state = TaidiRoomState.new(
        room_id=seed.room_id,
        host_id=seed.host_id,
        host_display_name=seed.host_display_name,
        now=seed.created_at,
    )
    taidi_state = taidi_machine.fold(taidi_state, await _load_taidi_events(session, room_id))
    return taidi_state, seed.invite_code, seed.game_type


async def rebuild_taidi_state_with_invite(
    session: AsyncSession, room_id: UUID
) -> tuple[TaidiRoomState, str]:
    state, invite_code, game_type = await rebuild_state_with_invite(session, room_id)
    if not isinstance(state, TaidiRoomState):
        raise WrongGameType(game_type, "taidi")
    return state, invite_code


async def rebuild_mahjong_state_with_invite(
    session: AsyncSession, room_id: UUID
) -> tuple[MahjongRoomState, str]:
    state, invite_code, game_type = await rebuild_state_with_invite(session, room_id)
    if not isinstance(state, MahjongRoomState):
        raise WrongGameType(game_type, "mahjong")
    return state, invite_code


_ROOM_STATUS_BY_EVENT_TYPE = {
    "game_started": "in_progress",
    "game_ended": "ended",
    "room_disbanded": "disbanded",
}


async def append_events(
    session: AsyncSession,
    room_id: UUID,
    new_events: list[TaidiEvent] | list[MahjongEvent],
    *,
    final_state: AnyRoomState | None = None,
) -> None:
    """Insert new events, and keep the stats read-model (rooms.status/
    ended_at, room_participants — see ADR-0007) and the settlements read-model
    (see the settlements table's comment in db.py) in sync with them, all in
    the same transaction as the events insert.

    `final_state` is the room's state already folded with `new_events` (the
    caller folds before calling this, rather than after, so the just-ended
    room's final `balances` are available here) — required to compute
    settlements on a game_ended transition; harmless to omit for any other
    call, since it's only consulted when new_status == "ended".

    Raises IntegrityError (unmapped) on a (room_id, seq) collision — the
    caller maps that to a 409 for the loser of a race.

    Event-type checks here are plain string comparisons rather than
    TaidiEventType/MahjongEventType membership checks, since both enums
    share the exact same string values for these types and new_events can
    be either — this keeps the hook game-type-agnostic.
    """
    if not new_events:
        return
    await session.execute(
        insert(events_table),
        [
            {
                "id": e.event_id,
                "room_id": room_id,
                "seq": e.seq,
                "type": e.type.value,
                "actor": e.actor,
                "payload": e.payload,
                "created_at": e.created_at,
            }
            for e in new_events
        ],
    )

    joins = [
        {
            "room_id": room_id,
            "player_id": UUID(e.payload["player_id"]),
            "joined_at": e.created_at,
        }
        for e in new_events
        if e.type.value == "player_joined"
    ]
    if joins:
        await session.execute(
            pg_insert(room_participants_table)
            .values(joins)
            .on_conflict_do_nothing(index_elements=["room_id", "player_id"])
        )

    for e in new_events:
        new_status = _ROOM_STATUS_BY_EVENT_TYPE.get(e.type.value)
        if new_status is None:
            continue
        values: dict[str, Any] = {"status": new_status}
        if new_status in ("ended", "disbanded"):
            values["ended_at"] = e.created_at
        await session.execute(
            update(rooms_table).where(rooms_table.c.room_id == room_id).values(**values)
        )

        # A disbanded room never had a real final result worth collecting
        # debts on — only a genuine game_ended transition settles up.
        if new_status == "ended" and final_state is not None:
            game_type = "mahjong" if isinstance(final_state, MahjongRoomState) else "taidi"
            rate = MAHJONG_CHIP_VALUE_CENTS if game_type == "mahjong" else 1
            raw_settlements = minimize_transfers(final_state.balances)
            if raw_settlements:
                await session.execute(
                    pg_insert(settlements_table)
                    .values(
                        [
                            {
                                "id": uuid4(),
                                "room_id": room_id,
                                "game_type": game_type,
                                "from_player": s.from_player,
                                "to_player": s.to_player,
                                "amount_cents": s.amount_cents * rate,
                                "status": "pending",
                                "created_at": e.created_at,
                                "updated_at": e.created_at,
                            }
                            for s in raw_settlements
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=["room_id", "from_player", "to_player"])
                )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
