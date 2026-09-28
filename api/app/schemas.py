"""Request bodies for the room command endpoints.

Every mutating command carries expected_seq (optimistic concurrency — see
taidi_core.machine and ADR-0001). Responses are always the full RoomState as
JSON (RoomState.model_dump(mode="json")), so the client never needs a second
round-trip to know what happened.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from mahjong_core.models import MahjongRules
from pydantic import BaseModel, Field
from taidi_core.models import MAX_CARDS, GameRules

# A card count is at least 1 (only the winner holds 0) and at most a deck.
CardCount = Annotated[int, Field(ge=1, le=MAX_CARDS)]
# Round/hand numbers the client saw, pinning a command to them — see
# dispatch.pinned_seq.
Pin = Annotated[int | None, Field(default=None, ge=1)]
Seat = Annotated[int, Field(ge=0, le=3)]


class CreateRoomRequest(BaseModel):
    game_type: Literal["taidi", "mahjong"] = "taidi"
    # Validated against the game's rules model in the create endpoint (the
    # shape depends on game_type), then kept as the room's draft rules.
    rules: dict[str, Any] | None = None


class StartGameRequest(BaseModel):
    expected_seq: int
    # Omitted: use the rules chosen at creation, else the defaults.
    rules: GameRules | None = None


class SeqOnlyRequest(BaseModel):
    expected_seq: int


class RoundCommandRequest(BaseModel):
    """A Taidi command about the current round (win, special, undo)."""

    expected_seq: int
    round_no: Pin = None


class HandCommandRequest(BaseModel):
    """A Mahjong command about the current hand (no-win, continue-wind)."""

    expected_seq: int
    hand_no: Pin = None


class SubmitCardsRequest(BaseModel):
    expected_seq: int
    cards: CardCount
    round_no: Pin = None


class SubmitForRequest(BaseModel):
    expected_seq: int
    target_player: UUID
    cards: CardCount
    round_no: Pin = None


class AssignSeatsRequest(BaseModel):
    expected_seq: int
    # A partial map (just the players being moved) is merged over the
    # current seats — see mahjong_core.machine.assign_seats.
    seat_map: dict[UUID, Seat] = Field(max_length=4)


class StartMahjongRequest(BaseModel):
    expected_seq: int
    rules: MahjongRules | None = None


class DeclareYaoRequest(BaseModel):
    expected_seq: int
    target_seat: Seat
    an: bool = False
    hand_no: Pin = None


class DeclareGangRequest(BaseModel):
    expected_seq: int
    target: Seat | Literal["angang"]
    hand_no: Pin = None


class DeclareHuRequest(BaseModel):
    expected_seq: int
    mode: Literal["direct", "zimo", "bao"]
    target_seat: Seat | None = None
    tai: Annotated[int, Field(ge=1, le=20)]
    zimo_bonus: bool = False
    klppdd: bool = False
    hand_no: Pin = None


class SetUsernameRequest(BaseModel):
    username: str = Field(max_length=64)


class SendFriendRequest(BaseModel):
    user_id: UUID
