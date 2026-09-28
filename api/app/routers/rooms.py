"""The room endpoints.

`create`/`by_code`/`get_state`/`active` are generic — they work for a room of
either game type, via events_store's AnyRoomState. Every other (mutating)
endpoint here is scoped to Taidi specifically: it goes through
dispatch.dispatch, which rebuilds the current TaidiRoomState from the event
log (rejecting a Mahjong room with 400 via WrongGameType), hands the command
to the matching taidi_core.machine function (which validates and returns
event(s) without mutating anything), persists those events, and returns the
freshly rebuilt state. See routers/mahjong.py for the equivalent Mahjong-
scoped endpoints. MachineError subclasses map directly to HTTP status codes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from mahjong_core.models import MahjongRules
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from taidi_core import machine
from taidi_core.models import Event, GameRules, RoomState, RoomStatus

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..dispatch import dispatch, pinned_seq
from ..events_store import (
    AlreadyInActiveRoom,
    AnyRoomState,
    RoomMeta,
    RoomNotFound,
    WrongGameType,
    create_room,
    ensure_no_other_active_room,
    find_active_room_state,
    load_room,
    resolve_invite_code,
)
from ..ratelimit import rate_limit
from ..schemas import (
    CreateRoomRequest,
    RoundCommandRequest,
    SeqOnlyRequest,
    StartGameRequest,
    SubmitCardsRequest,
    SubmitForRequest,
)
from ..time import utcnow
from ..users_service import ensure_user

router = APIRouter(prefix="/rooms", tags=["rooms"])


def raise_for_already_active(e: AlreadyInActiveRoom) -> NoReturn:
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        {"message": str(e), "active_room_id": str(e.room_id)},
    ) from e


def room_json(state: AnyRoomState, meta: RoomMeta) -> dict[str, Any]:
    return {
        **state.model_dump(mode="json"),
        "invite_code": meta.invite_code,
        "game_type": meta.game_type,
        "draft_rules": meta.draft_rules,
    }


def draft_rules_or_default[R: (GameRules, MahjongRules)](rules_type: type[R], meta: RoomMeta) -> R:
    """The rules to start with when the host didn't send any: what was
    picked on the create screen, else the defaults."""
    if meta.draft_rules is None:
        return rules_type()
    try:
        return rules_type.model_validate(meta.draft_rules)
    except ValidationError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The rules saved with this room are no longer valid — send rules to start.",
        ) from e


async def _load_taidi(session: AsyncSession, room_id: UUID) -> tuple[RoomState, RoomMeta]:
    try:
        state, meta = await load_room(session, room_id)
    except RoomNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found.") from e
    if not isinstance(state, RoomState):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, str(WrongGameType(meta.game_type, "taidi"))
        )
    return state, meta


def _round_seq(state: RoomState, expected_seq: int, round_no: int | None) -> int:
    current = state.rounds[-1].round_no if state.rounds else None
    return pinned_seq(expected_seq, round_no, current, state.seq)


async def _dispatch(
    session: AsyncSession, room_id: UUID, build_events: Callable[[RoomState], list[Event]]
) -> dict[str, Any]:
    return await dispatch(
        session,
        room_id,
        load=_load_taidi,
        fold=machine.fold,
        build_events=build_events,
        as_json=room_json,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: CreateRoomRequest = CreateRoomRequest(),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    draft: dict[str, Any] | None = None
    if body.rules is not None:
        rules_type: type[GameRules] | type[MahjongRules] = (
            MahjongRules if body.game_type == "mahjong" else GameRules
        )
        try:
            draft = rules_type.model_validate(body.rules).model_dump(mode="json")
        except ValidationError as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                [{"loc": ["body", "rules", *err["loc"]], "msg": err["msg"]} for err in e.errors()],
            ) from e
    await ensure_user(session, user)
    try:
        state, meta = await create_room(
            session,
            room_id=uuid4(),
            host_id=user.user_id,
            host_display_name=user.display_name,
            now=utcnow(),
            game_type=body.game_type,
            draft_rules=draft,
        )
    except AlreadyInActiveRoom as e:
        raise_for_already_active(e)
    return room_json(state, meta)


@router.get("/active")
async def active(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The room this player is currently in, if any — the way back into a
    live game from a device that has never seen its URL (see the one-active-
    room rule in events_store.find_active_room). `room_id` is null when
    they're not in one."""
    found = await find_active_room_state(session, user.user_id)
    if found is None:
        return {"room_id": None}
    room_id, state, meta = found
    return {
        "room_id": str(room_id),
        "invite_code": meta.invite_code,
        "game_type": meta.game_type,
        "status": state.status.value,
    }


@router.get("/by-code/{invite_code}", dependencies=[Depends(rate_limit("by-code", 30))])
async def by_code(invite_code: str, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Also returns game_type so the client can route straight to the right
    room component instead of spending a second round trip just to find out
    which one to render — see the room page's `g` query param.

    Rate limited: invite codes are short enough to guess at, and a guessed
    lobby is one anybody can join."""
    row = await resolve_invite_code(session, invite_code)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No room with that code.")
    room_id, game_type = row
    return {"room_id": str(room_id), "game_type": game_type}


def can_view(state: AnyRoomState, user_id: UUID) -> bool:
    """Lobbies are open to anyone holding the id — that's how joining by a
    shared link works. Once a game starts, its balances are real money
    results, so only the people who played (anyone holding a balance,
    including someone who stepped out) and the host can see it."""
    if state.status == RoomStatus.LOBBY:
        return True
    return user_id == state.host_id or user_id in state.balances


@router.get("/{room_id}/state")
async def get_state(
    room_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        state, meta = await load_room(session, room_id)
    except RoomNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Room not found.") from e
    if not can_view(state, user.user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You're not in this game.")
    return room_json(state, meta)


@router.post("/{room_id}/join")
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


@router.post("/{room_id}/leave")
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


@router.post("/{room_id}/disband")
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


@router.post("/{room_id}/start")
async def start(
    room_id: UUID,
    body: StartGameRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    _state, meta = await _load_taidi(session, room_id)
    rules = body.rules or draft_rules_or_default(GameRules, meta)
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


@router.post("/{room_id}/win")
async def win(
    room_id: UUID,
    body: RoundCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.claim_win(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/cards")
async def submit_cards(
    room_id: UUID,
    body: SubmitCardsRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.submit_cards(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            cards=body.cards,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/submit-for")
async def submit_for(
    room_id: UUID,
    body: SubmitForRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.submit_for(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            target_player=body.target_player,
            cards=body.cards,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/special")
async def special_hand(
    room_id: UUID,
    body: RoundCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.add_special_hand(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/step-out")
async def step_out(
    room_id: UUID,
    body: SeqOnlyRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Leave a game that's already running. One-way: the engine refuses
    mid-game joins, so there's no way back into this game afterwards. Your
    balance stays and settles with everyone else's — see machine.step_out."""
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.step_out(
            state, expected_seq=body.expected_seq, actor=user.user_id, now=utcnow()
        ),
    )


@router.post("/{room_id}/void-special")
async def void_special(
    room_id: UUID,
    body: RoundCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Take back your own accidental special-hand claim — see
    machine.void_special_hand for why voiding the round can't do it."""
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.void_special_hand(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/void")
async def void(
    room_id: UUID,
    body: RoundCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _dispatch(
        session,
        room_id,
        lambda state: machine.void_last_round(
            state,
            expected_seq=_round_seq(state, body.expected_seq, body.round_no),
            actor=user.user_id,
            now=utcnow(),
        ),
    )


@router.post("/{room_id}/end")
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
