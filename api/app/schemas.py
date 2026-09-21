"""Request bodies for the room command endpoints.

Every mutating command carries expected_seq (optimistic concurrency — see
taidi_core.machine and ADR-0001). Responses are always the full RoomState as
JSON (RoomState.model_dump(mode="json")), so the client never needs a second
round-trip to know what happened.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from mahjong_core.models import MahjongRules
from pydantic import BaseModel
from taidi_core.models import GameRules


class CreateRoomRequest(BaseModel):
    game_type: Literal["taidi", "mahjong"] = "taidi"


class StartGameRequest(BaseModel):
    expected_seq: int
    rules: GameRules = GameRules()


class SeqOnlyRequest(BaseModel):
    expected_seq: int


class SubmitCardsRequest(BaseModel):
    expected_seq: int
    cards: int


class SubmitForRequest(BaseModel):
    expected_seq: int
    target_player: UUID
    cards: int


class AssignSeatsRequest(BaseModel):
    expected_seq: int
    seat_map: dict[UUID, int]


class StartMahjongRequest(BaseModel):
    expected_seq: int
    rules: MahjongRules = MahjongRules()


class DeclareYaoRequest(BaseModel):
    expected_seq: int
    target_seat: int
    an: bool = False


class DeclareGangRequest(BaseModel):
    expected_seq: int
    target: int | Literal["angang"]


class DeclareHuRequest(BaseModel):
    expected_seq: int
    mode: Literal["direct", "zimo", "bao"]
    target_seat: int | None = None
    tai: int
    zimo_bonus: bool = False
    klppdd: bool = False


class SetUsernameRequest(BaseModel):
    username: str


class SendFriendRequest(BaseModel):
    user_id: UUID
