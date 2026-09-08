"""Typed vocabulary for mahjong_core: rules, hands, transfers, rooms, events.

Mirrors taidi_core/models.py's conventions (integer cents, frozen rule
models, event-sourced RoomState) but for Mahjong's very different shape:
no round-based card-count collection — a continuous stream of YAO/GANG/HU
declarations against an always-open hand, plus dealer/wind bookkeeping
Taidi has no equivalent of. See ADR-0006 for why this is a separate
package rather than a taidi_core extension.

Genuinely game-agnostic types (Member, Settlement, PlayerStats, RoomStatus,
the MachineError hierarchy) are imported from taidi_core rather than
duplicated here — see __init__.py.

Seats are plain ints 0-3, defaulting to join order; the host can rearrange
them via machine.assign_seats before starting. The 東南西北 nicknames are a
frontend display concern only — the backend never needs to know them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from taidi_core.models import Member, PlayerStats, RoomStatus


class TaiPayout(BaseModel):
    """One tai level's fixed payout. Real mahjong stakes tables aren't
    linear (a 5-tai hand pays far more than 5x a 1-tai hand), so this is a
    per-level lookup rather than a rate multiplied by tai."""

    model_config = ConfigDict(frozen=True)

    hu: int
    zimo: int


# "3/6 半" — the first real stakes table this app supports. Money is
# tracked in chips, not cents; base_chips is a starting stack used only for
# display (see RoomState docstring below), never part of the settlement math.
_DEFAULT_TAI_TABLE = {
    1: TaiPayout(hu=4, zimo=4),
    2: TaiPayout(hu=7, zimo=5),
    3: TaiPayout(hu=11, zimo=7),
    4: TaiPayout(hu=20, zimo=12),
    5: TaiPayout(hu=40, zimo=22),
}


class MahjongRules(BaseModel):
    """Everything about how a game is scored. All of it configurable."""

    model_config = ConfigDict(frozen=True)

    base_chips: int = 300
    yao_chips: int = 2
    gang_chips: int = 2
    # Optional extra bonuses layered on top of a HU's tai payout, each
    # toggled per-declaration (see machine.declare_hu). zimo_bonus only
    # applies to a self-drawn win; klppdd applies to any win and mirrors
    # whichever payer structure that win already uses (split 3 ways on a
    # zimo, paid in full by the single payer on a direct/bao win). Both
    # default to 0 (off) so existing presets are unaffected.
    zimo_bonus_chips: int = 0
    klppdd_chips: int = 0
    max_tai: int = 5
    tai_table: dict[int, TaiPayout] = Field(default_factory=lambda: dict(_DEFAULT_TAI_TABLE))

    @model_validator(mode="after")
    def _validate(self) -> MahjongRules:
        values = (
            self.base_chips,
            self.yao_chips,
            self.gang_chips,
            self.zimo_bonus_chips,
            self.klppdd_chips,
        )
        if min(values) < 0:
            raise ValueError("Rule values can't be negative.")
        if self.max_tai < 1:
            raise ValueError("max_tai must be at least 1.")
        missing = [t for t in range(1, self.max_tai + 1) if t not in self.tai_table]
        if missing:
            raise ValueError(f"tai_table is missing entries for tai={missing}.")
        return self

    def describe(self) -> str:
        top = self.tai_table[self.max_tai]
        extras = []
        if self.zimo_bonus_chips:
            extras.append(f"zimo bonus {self.zimo_bonus_chips}")
        if self.klppdd_chips:
            extras.append(f"klppdd {self.klppdd_chips}")
        extra = f" · {' · '.join(extras)}" if extras else ""
        return (
            f"base {self.base_chips} chips · yao {self.yao_chips} · gang {self.gang_chips} · "
            f"up to {self.max_tai} tai (hu {top.hu} / zimo {top.zimo}){extra}"
        )


class TransferKind(StrEnum):
    YAO = "yao"
    GANG = "gang"
    HU = "hu"
    BAO = "bao"
    ZIMO_BONUS = "zimo_bonus"
    KLPPDD = "klppdd"


class Transfer(BaseModel):
    """One payment from one player to another."""

    model_config = ConfigDict(frozen=True)

    from_player: UUID
    to_player: UUID
    amount_cents: int
    kind: TransferKind
    hand_no: int


class HandState(BaseModel):
    hand_no: int
    wind: int
    dealer_seat: int
    had_gang: bool = False
    closed: bool = False
    winner: UUID | None = None
    # Win-detail fields, folded from a HU_DECLARED event's payload (see
    # machine.apply) — stay at their defaults for an open or no-win hand.
    mode: Literal["direct", "zimo", "bao"] | None = None
    tai: int | None = None
    zimo_bonus: bool = False
    klppdd: bool = False
    transfers: list[Transfer] = Field(default_factory=list)


class RoomState(BaseModel):
    """The full, derivable state of one room. Rebuilt by folding events through
    machine.apply(). `balances` is always net (can go negative) — a player's
    displayed chip stack is `rules.base_chips + balances[player_id]`, computed
    by the caller, not stored here."""

    room_id: UUID
    status: RoomStatus = RoomStatus.LOBBY
    seq: int = 0
    host_id: UUID
    members: dict[UUID, Member] = Field(default_factory=dict)
    rules: MahjongRules | None = None
    hands: list[HandState] = Field(default_factory=list)
    balances: dict[UUID, int] = Field(default_factory=dict)
    created_at: datetime
    ended_at: datetime | None = None
    # Set once the 4-winds cycle completes (last seat of the last wind closes
    # on a win) — only the host's continue_wind or end_game can proceed.
    pending_wind_decision: bool = False

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
    def current_hand(self) -> HandState | None:
        return self.hands[-1] if self.hands else None

    @property
    def member_ids_by_seat(self) -> list[UUID]:
        """Member ids ordered by seat. Only meaningful once exactly 4 have joined."""
        return sorted(self.members, key=lambda pid: self.members[pid].seat)


class EventType(StrEnum):
    PLAYER_JOINED = "player_joined"
    SEATS_ASSIGNED = "seats_assigned"
    GAME_STARTED = "game_started"
    YAO_DECLARED = "yao_declared"
    GANG_DECLARED = "gang_declared"
    HU_DECLARED = "hu_declared"
    NO_WIN_DECLARED = "no_win_declared"
    WIND_CONTINUED = "wind_continued"
    GAME_ENDED = "game_ended"
    PLAYER_LEFT = "player_left"
    ROOM_DISBANDED = "room_disbanded"


class Event(BaseModel):
    """One entry in a room's append-only log. `payload` mirrors the `events.payload jsonb` column."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    room_id: UUID
    seq: int
    type: EventType
    actor: UUID | None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MahjongPlayerStats(BaseModel):
    """Hand-level stats, layered on top of the room-level `lifetime` figures
    from `player_lifetime_stats`. Only closed hands count toward
    hands_played; an open (in-progress) hand contributes nothing.
    "Dealer hands" uses the player's `Member.seat` (immutable once a game
    starts) against each hand's `dealer_seat` — no separate enrichment
    needed. `profit_by_kind` is chip-denominated, summed straight from
    existing `Transfer.kind` entries (no $-equivalent here — that
    conversion is a display-layer concern, not core domain logic)."""

    player_id: UUID
    display_name: str
    lifetime: PlayerStats

    hands_played: int = 0
    hu_count: int = 0
    hu_rate: float = 0.0

    win_mode_counts: dict[str, int] = Field(default_factory=dict)
    win_mode_rates: dict[str, float] = Field(default_factory=dict)

    avg_tai_on_wins: float = 0.0
    tai_distribution: dict[int, int] = Field(default_factory=dict)

    dealer_hands: int = 0
    dealer_wins: int = 0
    dealer_win_rate: float = 0.0

    profit_by_kind: dict[str, int] = Field(default_factory=dict)

    best_hand_chips: int | None = None
    worst_hand_chips: int | None = None
