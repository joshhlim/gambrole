"""The one write path every room command goes through, for both games.

Rebuild the room, run one command against it (the machine validates and
returns events without mutating anything), persist, return the new state.
routers/rooms.py and routers/mahjong.py used to each carry a copy of this
loop, and the copies drifted (retry counts, rollback handling) — so it lives
here once, parameterised by how to load, fold and serialise a room.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.errors import IllegalTransition, NotAuthorized, SeqConflict

from .events_store import RoomMeta, append_events

# Enough for every player at a full table to act in the same instant: pinned
# commands (see pinned_seq) land on the server's current seq, so a burst of
# them can collide at the DB several times before each one gets through.
DISPATCH_ATTEMPTS = 5


def pinned_seq(expected_seq: int, pin: int | None, current: int | None, seq: int) -> int:
    """The seq a command is checked against.

    Most commands are held to the seq the client last saw, so anything that
    landed in between makes them fail with a 409 and a fresh state. That's
    wrong for commands that don't conflict with each other — two players'
    card counts, one player's yao and another's gang — and worse, a client
    that blindly retries such a 409 against the fresh seq can land its
    command on the NEXT round or hand (a void that undoes the round that
    just paid out, a second no-win that closes the following hand).

    So round/hand-scoped commands name the round or hand they're about
    (`pin`). When they do, only that is checked, and the command lands on
    whatever seq the room is at now; if the round or hand has moved on it's
    refused, so nothing is ever applied to one the player didn't see.
    Without a pin (an older client) the strict seq check still applies.
    """
    if pin is None:
        return expected_seq
    if current != pin:
        raise SeqConflict(expected=expected_seq, actual=seq)
    return seq


def acting_as(state: Any, user_id: UUID, as_player: UUID | None) -> UUID:
    """Who a command is for. Normally the caller; the host may instead act
    for a guest at the table (someone with no account, whose turns the host
    enters on one shared phone). Anyone else asking is refused — raised as
    NotAuthorized inside build_events, so dispatch maps it to a 403."""
    if as_player is None or as_player == user_id:
        return user_id
    if user_id != state.host_id:
        raise NotAuthorized("Only the host can act for a guest.")
    member = state.members.get(as_player)
    if member is None or not member.is_guest:
        raise NotAuthorized("You can only act for a guest at this table.")
    return as_player


async def dispatch[S](
    session: AsyncSession,
    room_id: UUID,
    *,
    load: Callable[[AsyncSession, UUID], Awaitable[tuple[S, RoomMeta]]],
    fold: Callable[[S, list[Any]], S],
    build_events: Callable[[S], list[Any]],
    as_json: Callable[[S, RoomMeta], dict[str, Any]],
) -> dict[str, Any]:
    """Retries a genuine DB-level race (two requests computing the same next
    seq); each retry rebuilds fresh state and re-validates, so it either
    succeeds against the now-current state or raises a proper MachineError
    instead of a raw integrity error."""
    for _attempt in range(DISPATCH_ATTEMPTS):
        state, meta = await load(session, room_id)
        try:
            new_events = build_events(state)
        except SeqConflict as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Someone else acted first.", "state": as_json(state, meta)},
            ) from e
        except NotAuthorized as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
        except IllegalTransition as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

        new_state = fold(state, new_events)
        try:
            await append_events(session, room_id, new_events, final_state=new_state)  # type: ignore[arg-type]
        except IntegrityError:
            continue  # append_events rolled back; someone else's event landed first

        return as_json(new_state, meta)

    state, meta = await load(session, room_id)
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        {"message": "Too many people acted at once — try again.", "state": as_json(state, meta)},
    )
