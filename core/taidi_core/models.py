"""Typed vocabulary for taidi_core: rules, transfers, rounds, rooms, events.

Money is always integer cents. Player identity is always a UUID; display
names live only on Member/PlayerStats. RoomState is treated as immutable —
`machine.apply()` returns a new instance rather than mutating its input.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GameRules(BaseModel):
    """Everything about how a game is scored. All of it configurable."""

    model_config = ConfigDict(frozen=True)

    card_value_cents: int = 20
    base_cards: int = 2
    multipliers_enabled: bool = True
    double_threshold: int = 10
    triple_threshold: int = 13
    difference_payouts: bool = True
    special_hands_enabled: bool = True
    special_hand_cards: int = 5

    @model_validator(mode="after")
    def _validate(self) -> GameRules:
        if min(self.card_value_cents, self.base_cards, self.special_hand_cards) < 0:
            raise ValueError("Rule values can't be negative.")
        if self.multipliers_enabled and self.triple_threshold < self.double_threshold:
            raise ValueError("triple_threshold must be >= double_threshold.")
        return self

    def multiplier(self, payer_cards: int) -> int:
        if not self.multipliers_enabled:
            return 1
        if payer_cards >= self.triple_threshold:
            return 3
        if payer_cards >= self.double_threshold:
            return 2
        return 1

    def describe(self) -> str:
        parts = [f"${self.card_value_cents / 100:.2f}/card"]
        if self.base_cards:
            parts.append(f"base {self.base_cards}")
        if self.multipliers_enabled:
            parts.append(f"x2 at {self.double_threshold}+, x3 at {self.triple_threshold}+")
        else:
            parts.append("no multipliers")
        parts.append("difference payouts" if self.difference_payouts else "winner-only")
        if self.special_hands_enabled:
            parts.append(f"special +{self.special_hand_cards}")
        return " · ".join(parts)


class TransferKind(StrEnum):
    CARDS = "cards"
    DIFFERENCE = "difference"
    BASE = "base"
    SPECIAL = "special"


class Transfer(BaseModel):
    """One payment from one player to another. Kind names match the legacy engine."""

    model_config = ConfigDict(frozen=True)

    from_player: UUID
    to_player: UUID
    cards: int
    mult: int = 1
    amount_cents: int
    kind: TransferKind
    round_no: int


class RoundPhase(StrEnum):
    PLAYING = "playing"
    COLLECTING = "collecting"
    RESOLVED = "resolved"


class RoundState(BaseModel):
    round_no: int
    phase: RoundPhase = RoundPhase.PLAYING
    winner: UUID | None = None
    cards_submitted: dict[UUID, int] = Field(default_factory=dict)
    special_counts: dict[UUID, int] = Field(default_factory=dict)
    rules_snapshot: GameRules | None = None
    engine_version: str | None = None
    transfers: list[Transfer] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """True for a fresh round that nothing has happened in yet (nothing to void)."""
        return self.phase == RoundPhase.PLAYING and not self.transfers


class Member(BaseModel):
    player_id: UUID
    display_name: str
    is_guest: bool = False
    seat: int


class RoomStatus(StrEnum):
    LOBBY = "lobby"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    DISBANDED = "disbanded"


class RoomState(BaseModel):
    """The full, derivable state of one room. Rebuilt by folding events through machine.apply()."""

    room_id: UUID
    status: RoomStatus = RoomStatus.LOBBY
    seq: int = 0
    host_id: UUID
    members: dict[UUID, Member] = Field(default_factory=dict)
    rules: GameRules | None = None
    rounds: list[RoundState] = Field(default_factory=list)
    balances: dict[UUID, int] = Field(default_factory=dict)
    created_at: datetime
    ended_at: datetime | None = None

    @classmethod
    def new(
        cls, *, room_id: UUID, host_id: UUID, host_display_name: str, now: datetime
    ) -> RoomState:
        host = Member(player_id=host_id, display_name=host_display_name, seat=0)
        return cls(
            room_id=room_id,
            host_id=host_id,
            members={host_id: host},
            balances={host_id: 0},
            created_at=now,
        )

    @property
    def current_round(self) -> RoundState | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def member_ids(self) -> list[UUID]:
        """Member ids in join order."""
        return sorted(self.members, key=lambda pid: self.members[pid].seat)


class EventType(StrEnum):
    PLAYER_JOINED = "player_joined"
    GAME_STARTED = "game_started"
    WIN_CLAIMED = "win_claimed"
    CARDS_SUBMITTED = "cards_submitted"
    SPECIAL_HAND = "special_hand"
    ROUND_RESOLVED = "round_resolved"
    ROUND_VOIDED = "round_voided"
    SUBMITTED_FOR = "submitted_for"
    GAME_ENDED = "game_ended"
    PLAYER_LEFT = "player_left"
    ROOM_DISBANDED = "room_disbanded"


class Event(BaseModel):
    """One entry in a room's append-only log. `payload` mirrors the future `events.data jsonb` column."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    room_id: UUID
    seq: int
    type: EventType
    actor: UUID | None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PlayerStats(BaseModel):
    player_id: UUID
    display_name: str
    games: int = 0
    total_cents: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    last_played: datetime | None = None

    @property
    def avg_cents(self) -> float:
        return self.total_cents / self.games if self.games else 0.0


class Settlement(BaseModel):
    from_player: UUID
    to_player: UUID
    amount_cents: int


class SettlementStatus(StrEnum):
    """Lifecycle of a persisted Settlement (see api/app/db.py's `settlements`
    table). No REJECTED value: rejecting a marked_paid claim is an action
    that reverts status to PENDING, not a fourth resting state."""

    PENDING = "pending"
    MARKED_PAID = "marked_paid"
    APPROVED = "approved"


class TaidiPlayerStats(BaseModel):
    """Round-level stats, layered on top of the room-level `lifetime`
    figures from `player_lifetime_stats`. Only RESOLVED rounds count toward
    rounds_played/round_wins/profit/double/triple — a round can survive
    into an ended room's final state without resolving (e.g. a win was
    claimed but cards were never fully submitted before the host ended the
    game), and those have no rules_snapshot to compare card counts against.
    `special_hands_claimed` is not phase-gated: specials settle immediately
    and independently of round resolution.

    double_rate/triple_rate are fractions of payer_rounds (rounds the
    player did NOT win — the only rounds GameRules.multiplier ever applies
    to, since it's keyed off the payer's own remaining card count), not of
    rounds_played. payer_rounds is exposed alongside them so a caller can
    show "N of M losing rounds" rather than a bare, easy-to-misread
    percentage."""

    player_id: UUID
    display_name: str
    lifetime: PlayerStats

    rounds_played: int = 0
    round_wins: int = 0
    round_win_rate: float = 0.0

    profit_rounds: int = 0
    profit_rate: float = 0.0

    payer_rounds: int = 0
    double_rounds: int = 0
    double_rate: float = 0.0
    triple_rounds: int = 0
    triple_rate: float = 0.0

    special_hands_claimed: int = 0

    best_round_cents: int | None = None
    worst_round_cents: int | None = None
