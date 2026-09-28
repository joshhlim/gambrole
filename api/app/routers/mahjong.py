"""The Mahjong room endpoints.

Mirrors routers/rooms.py's shape exactly (see that file's docstring and
ADR-0006) but scoped to Mahjong: every endpoint here goes through
dispatch.dispatch with a MahjongRoomState (rejecting a Taidi room with 400
via WrongGameType), hands the command to the matching mahjong_core.machine
function, persists the resulting events, and returns the freshly rebuilt
state.

`create`/`by-code`/`get-state` are NOT duplicated here — they're generic
and already live in routers/rooms.py.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from mahjong_core import machine
from mahjong_core.models import Event, MahjongRules, RoomState
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..dispatch import dispatch, pinned_seq
from ..events_store import (
    AlreadyInActiveRoom,
    RoomMeta,
    RoomNotFound,
    WrongGameType,
    ensure_no_other_active_room,
    load_room,
)
from ..schemas import (
    AssignSeatsRequest,
    DeclareGangRequest,
    DeclareHuRequest,
    DeclareYaoRequest,
    HandCommandRequest,
    SeqOnlyRequest,
    StartMahjongRequest,
)
from ..time import utcnow
from ..users_service import ensure_user
from .rooms import draft_rules_or_default, raise_for_already_active, room_json

router = APIRouter(prefix="/rooms/{room_id}/mahjong", tags=["mahjong"])


async def _load_mahjong(session: AsyncSession, room_id: UUID) -> tuple[RoomState, RoomMeta]:
    try:
        state, meta = await load_room(session, room_id)
    except RoomNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found.") from e
    if not isinstance(state, RoomState):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(WrongGameType(meta.game_type, "mahjong"))
        )
    return state, meta


def _hand_seq(state: RoomState, expected_seq: int, hand_no: int | None) -> int:
    current = state.hands[-1].hand_no if state.hands else None
    return pinned_seq(expected_seq, hand_no, current, state.seq)


async def _dispatch(
    session: AsyncSession, room_id: UUID, build_events: Callable[[RoomState], list[Event]]
) -> dict[str, Any]:
    return await dispatch(
        session,
        room_id,
        load=_load_mahjong,
        fold=machine.fold,
        build_events=build_events,
        as_json=room_json,
    )


@router.post("/join")
async def join(
    room_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    try:
        await ensure_no_other_active_room(session, user.user_id, excluding_room_id=room_id)
    except AlreadyInActiveRoom as e:
        raise_for_already_active(e)
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
    _state, meta = await _load_mahjong(session, room_id)
    rules = body.rules or draft_rules_or_default(MahjongRules, meta)
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.start_game(
            state,
            expected_seq=body.expected_seq,
            actor=user.user_id,
            rules=rules,
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
            expected_seq=_hand_seq(state, body.expected_seq, body.hand_no),
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
            expected_seq=_hand_seq(state, body.expected_seq, body.hand_no),
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
            expected_seq=_hand_seq(state, body.expected_seq, body.hand_no),
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
    body: HandCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.declare_no_win(
            state,
            expected_seq=_hand_seq(state, body.expected_seq, body.hand_no),
            actor=user.user_id,
            now=utcnow(),
        ),
    )


@router.post("/continue-wind")
async def continue_wind(
    room_id: UUID,
    body: HandCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.continue_wind(
            state,
            expected_seq=_hand_seq(state, body.expected_seq, body.hand_no),
            actor=user.user_id,
            now=utcnow(),
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
