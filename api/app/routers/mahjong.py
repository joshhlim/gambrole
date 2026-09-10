"""The Mahjong room endpoints.

Mirrors routers/rooms.py's shape exactly (see that file's docstring and
ADR-0006) but scoped to Mahjong: every endpoint here rebuilds a
MahjongRoomState (rejecting a Taidi room with 400 via WrongGameType), hands
the command to the matching mahjong_core.machine function, persists the
resulting events, and returns the freshly rebuilt state.

`create`/`by-code`/`get-state` are NOT duplicated here — they're generic
and already live in routers/rooms.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from mahjong_core import machine
from mahjong_core.models import Event, RoomState
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core.errors import IllegalTransition, NotAuthorized, SeqConflict

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..events_store import (
    AlreadyInActiveRoom,
    RoomNotFound,
    WrongGameType,
    append_events,
    ensure_no_other_active_room,
    rebuild_mahjong_state_with_invite,
)
from ..schemas import (
    AssignSeatsRequest,
    DeclareGangRequest,
    DeclareHuRequest,
    DeclareYaoRequest,
    SeqOnlyRequest,
    StartMahjongRequest,
)
from ..time import utcnow

router = APIRouter(prefix="/rooms/{room_id}/mahjong", tags=["mahjong"])


async def _get_mahjong_state_or_404(session: AsyncSession, room_id: UUID) -> tuple[RoomState, str]:
    try:
        return await rebuild_mahjong_state_with_invite(session, room_id)
    except RoomNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found.") from e
    except WrongGameType as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


def _raise_for_already_active(e: AlreadyInActiveRoom) -> NoReturn:
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        {"message": str(e), "active_room_id": str(e.room_id)},
    ) from e


def _as_json(state: RoomState, invite_code: str) -> dict[str, Any]:
    return {**state.model_dump(mode="json"), "invite_code": invite_code, "game_type": "mahjong"}


async def _dispatch(
    session: AsyncSession,
    room_id: UUID,
    build_events: Callable[[RoomState], list[Event]],
) -> dict[str, Any]:
    """See routers/rooms.py's _dispatch — identical shape, mahjong_core.machine instead."""
    for _attempt in range(2):
        state, invite_code = await _get_mahjong_state_or_404(session, room_id)
        try:
            new_events = build_events(state)
        except SeqConflict as e:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": str(e), "state": _as_json(state, invite_code)},
            ) from e
        except NotAuthorized as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
        except IllegalTransition as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

        new_state = machine.fold(state, new_events)
        try:
            await append_events(session, room_id, new_events, final_state=new_state)
        except IntegrityError:
            continue  # someone else's event landed first — rebuild and retry once

        return _as_json(new_state, invite_code)

    raise HTTPException(status.HTTP_409_CONFLICT, "Too many concurrent updates — please retry.")


@router.post("/join")
async def join(
    room_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await ensure_no_other_active_room(session, user.user_id, excluding_room_id=room_id)
    except AlreadyInActiveRoom as e:
        _raise_for_already_active(e)
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.join_player(
            state,
            expected_seq=state.seq,
            player_id=user.user_id,
            display_name=user.display_name,
            now=utcnow(),
        ),
    )


@router.post("/leave")
async def leave(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.leave_room(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )


@router.post("/disband")
async def disband(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.disband_room(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )


@router.post("/assign-seats")
async def assign_seats(
    room_id: UUID,
    body: AssignSeatsRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.assign_seats(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            seat_map=body.seat_map,
            now=utcnow(),
        ),
    )


@router.post("/start")
async def start(
    room_id: UUID,
    body: StartMahjongRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.start_game(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            rules=body.rules,
            now=utcnow(),
        ),
    )


@router.post("/yao")
async def yao(
    room_id: UUID,
    body: DeclareYaoRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.declare_yao(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            target_seat=body.target_seat,
            an=body.an,
            now=utcnow(),
        ),
    )


@router.post("/gang")
async def gang(
    room_id: UUID,
    body: DeclareGangRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.declare_gang(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            target=body.target,
            now=utcnow(),
        ),
    )


@router.post("/hu")
async def hu(
    room_id: UUID,
    body: DeclareHuRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.declare_hu(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            mode=body.mode,
            target_seat=body.target_seat,
            tai=body.tai,
            zimo_bonus=body.zimo_bonus,
            klppdd=body.klppdd,
            now=utcnow(),
        ),
    )


@router.post("/no-win")
async def no_win(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.declare_no_win(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )


@router.post("/continue-wind")
async def continue_wind(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.continue_wind(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )


@router.post("/end")
async def end(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.end_game(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )
