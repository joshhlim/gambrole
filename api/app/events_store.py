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
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from mahjong_core import machine as mahjong_machine
from mahjong_core.models import Event as MahjongEvent
from mahjong_core.models import EventType as MahjongEventType
from mahjong_core.models import RoomState as MahjongRoomState
from sqlalchemy import insert, select, union, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core import machine as taidi_machine
from taidi_core.errors import IllegalTransition
from taidi_core.models import Event as TaidiEvent
from taidi_core.models import EventType as TaidiEventType
from taidi_core.models import RoomState as TaidiRoomState
from taidi_core.models import RoomStatus
from taidi_core.settlement import minimize_transfers

from .config import settings
from .db import events as events_table
from .db import room_participants as room_participants_table
from .db import rooms as rooms_table
from .db import settlements as settlements_table
from .money import MAHJONG_CHIP_VALUE_CENTS
from .time import utcnow

AnyRoomState = TaidiRoomState | MahjongRoomState

# Written into a game_ended event's payload when the inactivity backstop
# closed the game rather than a player. Read back by history/debts so a
# surprise debt can be explained. See _maybe_close_stale_room.
STALE_REASON = "stale"

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


class AlreadyInActiveRoom(Exception):
    """Raised when a player tries to create or join a new room while
    already hosting or participating in another lobby/in_progress room —
    a player is limited to one active room at a time."""

    def __init__(self, room_id: UUID):
        self.room_id = room_id
        super().__init__("You're already in an active room — finish or leave it first.")


async def find_active_room(session: AsyncSession, player_id: UUID) -> UUID | None:
    """The room `player_id` is actually in right now — hosting, or joined
    and not since left — that hasn't ended or been disbanded, if any.

    The SQL only narrows down *candidates*: `room_participants` is a
    historical index of who has ever joined a room (a player_left never
    removes the row — see ADR-0007 and scripts/backfill_stats_infra.py), so
    it can't answer "is this player in the room now". Each candidate is
    confirmed against the folded event log, which is what actually defines
    membership — and rebuilding also gives a stale room the chance to
    auto-close rather than block the player forever.
    """
    as_host = select(rooms_table.c.room_id).where(
        rooms_table.c.host_id == player_id,
        rooms_table.c.status.in_(("lobby", "in_progress")),
    )
    as_participant = (
        select(rooms_table.c.room_id)
        .select_from(
            room_participants_table.join(
                rooms_table, room_participants_table.c.room_id == rooms_table.c.room_id
            )
        )
        .where(
            room_participants_table.c.player_id == player_id,
            rooms_table.c.status.in_(("lobby", "in_progress")),
        )
    )
    candidates = (await session.execute(union(as_host, as_participant))).all()
    for candidate in candidates:
        state, events, machine, _invite_code, _game_type = await _rebuild(
            session, candidate.room_id
        )
        # The one spot the staleness backstop runs: a stale room's only real
        # harm is locking its members out of starting another one, so close
        # it exactly where that would happen. Keeping it out of the plain
        # read path means browsing stats/debts/history never mutates a room,
        # and a lobby can't disband while someone sits watching it poll.
        state = await _maybe_close_stale_room(session, candidate.room_id, state, events, machine)
        if (
            state.status in (RoomStatus.LOBBY, RoomStatus.IN_PROGRESS)
            and player_id in state.members
        ):
            return cast(UUID, candidate.room_id)
    return None


async def ensure_no_other_active_room(
    session: AsyncSession, player_id: UUID, *, excluding_room_id: UUID | None = None
) -> None:
    """Best-effort, not a hard guarantee: two requests racing here can both
    pass before either room exists, leaving a player in two active rooms.
    The window is milliseconds, the client disables the button while a
    create is in flight, and the stray room auto-closes once it goes stale —
    so this deliberately isn't backed by a DB constraint (which would need a
    whole extra table kept in sync with the event log)."""
    active_room_id = await find_active_room(session, player_id)
    if active_room_id is not None and active_room_id != excluding_room_id:
        raise AlreadyInActiveRoom(active_room_id)


async def create_room(
    session: AsyncSession,
    *,
    room_id: UUID,
    host_id: UUID,
    host_display_name: str,
    now: datetime,
    game_type: str = "taidi",
) -> tuple[AnyRoomState, str, str]:
    await ensure_no_other_active_room(session, host_id)
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


async def resolve_invite_code(session: AsyncSession, invite_code: str) -> tuple[UUID, str] | None:
    """Returns (room_id, game_type) — the game type rides along so a joining
    client can route to the right room component without a second request."""
    row = (
        await session.execute(
            select(rooms_table.c.room_id, rooms_table.c.game_type).where(
                rooms_table.c.invite_code == invite_code.upper()
            )
        )
    ).first()
    return (row.room_id, row.game_type) if row else None


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


async def _rebuild(
    session: AsyncSession, room_id: UUID
) -> tuple[AnyRoomState, list[TaidiEvent] | list[MahjongEvent], Any, str, str]:
    """Fold a room's event log, returning the raw events and the matching
    machine module alongside the state — so a caller that needs to act on
    the room (the staleness backstop) doesn't re-load or re-derive them."""
    seed = await _load_room_seed(session, room_id)
    if seed.game_type == "mahjong":
        mahjong_state = MahjongRoomState.new(
            room_id=seed.room_id,
            host_id=seed.host_id,
            host_display_name=seed.host_display_name,
            now=seed.created_at,
        )
        mahjong_events = await _load_mahjong_events(session, room_id)
        return (
            mahjong_machine.fold(mahjong_state, mahjong_events),
            mahjong_events,
            mahjong_machine,
            seed.invite_code,
            seed.game_type,
        )

    taidi_state = TaidiRoomState.new(
        room_id=seed.room_id,
        host_id=seed.host_id,
        host_display_name=seed.host_display_name,
        now=seed.created_at,
    )
    taidi_events = await _load_taidi_events(session, room_id)
    return (
        taidi_machine.fold(taidi_state, taidi_events),
        taidi_events,
        taidi_machine,
        seed.invite_code,
        seed.game_type,
    )


async def _maybe_close_stale_room(
    session: AsyncSession,
    room_id: UUID,
    state: AnyRoomState,
    events: list[TaidiEvent] | list[MahjongEvent],
    machine: Any,
) -> AnyRoomState:
    """Close a room nobody has touched in a while.

    There's no presence/heartbeat tracking in this app (plain REST +
    polling) — a host who walks away without disbanding/ending a room would
    otherwise leave it open forever with no way for anyone else to close it,
    and with one-active-room-per-player that locks every member out of
    starting another game. Only ever acts once per room: the closing event
    moves `status` out of lobby/in_progress, so the next check returns
    immediately.

    A stale lobby is disbanded (no game was played, nothing to settle). A
    stale in-progress game is ended, marked `reason: stale` so it can be
    told apart from a game its players chose to end — whatever the balances
    are at that point become the final result and settle as usual.
    """
    if state.status == RoomStatus.LOBBY:
        threshold = timedelta(hours=settings.lobby_stale_hours)
    elif state.status == RoomStatus.IN_PROGRESS:
        threshold = timedelta(hours=settings.in_progress_stale_hours)
    else:
        return state

    last_activity = events[-1].created_at if events else state.created_at
    if utcnow() - last_activity < threshold:
        return state

    now = utcnow()
    if state.status == RoomStatus.LOBBY:
        closing_events = machine.disband_room(
            state, expected_seq=state.seq, actor=state.host_id, now=now
        )
        new_state = machine.fold(state, closing_events)
    else:
        try:
            closing_events = machine.end_game(
                state, expected_seq=state.seq, actor=state.host_id, now=now, reason=STALE_REASON
            )
            new_state = machine.fold(state, closing_events)
        except IllegalTransition:
            # Taidi refuses to end a game while a round is still being
            # collected — someone claimed a win and a player never entered
            # their card count. Nothing in the UI can void that round, so
            # without this the game could NEVER close and every member would
            # be locked out of the app for good. Drop the unfinished round
            # (it never completed, so its money isn't real) and end.
            void_events = machine.void_last_round(
                state, expected_seq=state.seq, actor=state.host_id, now=now
            )
            voided = machine.fold(state, void_events)
            end_events = machine.end_game(
                voided, expected_seq=voided.seq, actor=voided.host_id, now=now, reason=STALE_REASON
            )
            closing_events = [*void_events, *end_events]
            new_state = machine.fold(voided, end_events)

    await append_events(session, room_id, closing_events, final_state=new_state)
    return cast(AnyRoomState, new_state)


async def rebuild_state(session: AsyncSession, room_id: UUID) -> AnyRoomState:
    state, _invite_code, _game_type = await rebuild_state_with_invite(session, room_id)
    return state


async def rebuild_state_with_invite(
    session: AsyncSession, room_id: UUID
) -> tuple[AnyRoomState, str, str]:
    """Rebuilds whichever RoomState type matches the room's stored
    game_type. Generic endpoints (get-state, create) use this directly;
    each game's router narrows via rebuild_taidi_state_with_invite /
    rebuild_mahjong_state_with_invite instead.

    Pure: reading a room never writes to it. The staleness backstop lives in
    find_active_room instead, so polling a lobby can't disband it underfoot
    and opening /debts can't end someone else's game."""
    state, _events, _machine, invite_code, game_type = await _rebuild(session, room_id)
    return state, invite_code, game_type


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
