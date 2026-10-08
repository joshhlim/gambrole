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

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationInfo, model_validator
from taidi_core.models import Member, PlayerStats, RoomStatus, is_replay

# Caps on rule values. Generous for any real table; they exist so a typo
# (or a hostile client) can't produce amounts that overflow storage, or a
# max_tai large enough to stall the server building the table.
MAX_TAI = 20
MAX_TAI_PAYOUT = 1_000_000
MAX_ACTION_AMOUNT = 100_000

# Games before amounts became dollars were scored in chips worth $0.50. A
# stored rule set without `cents_per_unit` is one of those; this is what
# its amounts are multiplied by (see MahjongRules.cents_per_unit).
LEGACY_CENTS_PER_CHIP = 50


class TaiPayout(BaseModel):
    """One tai level's fixed payout. Real mahjong stakes tables aren't
    linear (a 5-tai hand pays far more than 5x a 1-tai hand), so this is a
    per-level lookup rather than a rate multiplied by tai."""

    model_config = ConfigDict(frozen=True)

    hu: int
    zimo: int

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> TaiPayout:
        # A validator rather than Field bounds so replay can skip it — see
        # taidi_core.models.REPLAY.
        if not is_replay(info) and not (
            0 <= self.hu <= MAX_TAI_PAYOUT and 0 <= self.zimo <= MAX_TAI_PAYOUT
        ):
            raise ValueError(f"Tai payouts must be between 0 and {MAX_TAI_PAYOUT}.")
        return self


# "3/6 半" — the first real stakes table this app supports, in cents. (It
# was 4/7/11/20/40 chips at $0.50 a chip; these are the same amounts.)
_DEFAULT_TAI_TABLE = {
    1: TaiPayout(hu=200, zimo=200),
    2: TaiPayout(hu=350, zimo=250),
    3: TaiPayout(hu=550, zimo=350),
    4: TaiPayout(hu=1000, zimo=600),
    5: TaiPayout(hu=2000, zimo=1100),
}


def _amount(default: int, legacy_name: str) -> Any:
    # Accepts the pre-dollars field name too, so stored games and older
    # clients keep validating; always serialised under the new name.
    name = legacy_name.removesuffix("_chips") + "_amount"
    return Field(default=default, validation_alias=AliasChoices(name, legacy_name))


class MahjongRules(BaseModel):
    """Everything about how a game is scored. All of it configurable.

    Amounts are in units of `cents_per_unit`: 1 for every game created since
    money became dollars (amounts ARE cents), 50 for older games scored in
    $0.50 chips. machine.apply multiplies every transfer by it, so state,
    stats and settlements only ever see cents."""

    model_config = ConfigDict(frozen=True)

    cents_per_unit: int = 1
    yao_amount: int = _amount(100, "yao_chips")
    gang_amount: int = _amount(100, "gang_chips")
    # Optional extra bonuses layered on top of a HU's tai payout, each
    # toggled per-declaration (see machine.declare_hu). zimo_bonus only
    # applies to a self-drawn win; klppdd applies to any win and mirrors
    # whichever payer structure that win already uses (split 3 ways on a
    # zimo, paid in full by the single payer on a direct/bao win). Both
    # default to 0 (off) so existing presets are unaffected.
    zimo_bonus_amount: int = _amount(0, "zimo_bonus_chips")
    klppdd_amount: int = _amount(0, "klppdd_chips")
    max_tai: int = 5
    tai_table: dict[int, TaiPayout] = Field(default_factory=lambda: dict(_DEFAULT_TAI_TABLE))

    @model_validator(mode="after")
    def _validate(self, info: ValidationInfo) -> MahjongRules:
        if is_replay(info):
            return self
        values = (self.yao_amount, self.gang_amount, self.zimo_bonus_amount, self.klppdd_amount)
        if min(values) < 0:
            raise ValueError("Rule values can't be negative.")
        if max(values) > MAX_ACTION_AMOUNT:
            raise ValueError("Rule values are too large.")
        if not 1 <= self.cents_per_unit <= LEGACY_CENTS_PER_CHIP:
            raise ValueError(f"cents_per_unit must be between 1 and {LEGACY_CENTS_PER_CHIP}.")
        if not 1 <= self.max_tai <= MAX_TAI:
            raise ValueError(f"max_tai must be between 1 and {MAX_TAI}.")
        if len(self.tai_table) > MAX_TAI or any(not 1 <= t <= MAX_TAI for t in self.tai_table):
            raise ValueError(f"tai_table levels must be between 1 and {MAX_TAI}.")
        missing = [t for t in range(1, self.max_tai + 1) if t not in self.tai_table]
        if missing:
            raise ValueError(f"tai_table is missing entries for tai={missing}.")
        return self

    @classmethod
    def from_stored(cls, raw: dict[str, Any], **kwargs: Any) -> MahjongRules:
        """Validate rules that may predate dollars — for stored games and for
        anything an older client sends. Those always carry the old `*_chips`
        field names (every stored rule set is a full dump) and never a
        `cents_per_unit`; anything else is already in cents."""
        is_chips = "cents_per_unit" not in raw and any(k.endswith("_chips") for k in raw)
        if is_chips:
            raw = {"cents_per_unit": LEGACY_CENTS_PER_CHIP, **raw}
        return cls.model_validate(raw, **kwargs)

    def describe(self) -> str:
        def money(units: int) -> str:
            return f"${units * self.cents_per_unit / 100:.2f}"

        top = self.tai_table[self.max_tai]
        extras = []
        if self.zimo_bonus_amount:
            extras.append(f"zimo bonus {money(self.zimo_bonus_amount)}")
        if self.klppdd_amount:
            extras.append(f"klppdd {money(self.klppdd_amount)}")
        extra = f" · {' · '.join(extras)}" if extras else ""
        return (
            f"yao {money(self.yao_amount)} · gang {money(self.gang_amount)} · "
            f"up to {self.max_tai} tai (hu {money(top.hu)} / zimo {money(top.zimo)}){extra}"
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


class Declaration(BaseModel):
    """A YAO or GANG someone declared during a hand, and whether it was the
    concealed variant (anyao / angang).

    The transfers a declaration produces can't answer this on their own: a
    self-drawn yao and an angang both bill all three opponents, and they're
    told apart only by amount, which depends on the rules in force. The
    declaring event has always recorded it (`an` / `target`), so folding it
    into state here makes the distinction available to stats — including
    for games played before this existed, since replay reads the same
    payloads."""

    model_config = ConfigDict(frozen=True)

    player_id: UUID
    kind: Literal["yao", "gang"]
    concealed: bool


class HandState(BaseModel):
    hand_no: int
    wind: int
    dealer_seat: int
    had_gang: bool = False
    declarations: list[Declaration] = Field(default_factory=list)
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
    machine.apply(). `balances` is always net cents (can go negative)."""

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
    needed. `profit_by_kind` is in cents, summed straight from existing
    `Transfer.kind` entries."""

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

    best_hand_cents: int | None = None
    worst_hand_cents: int | None = None


class MahjongSessionFacts(BaseModel):
    """One ended Mahjong room, reduced to counters for one player. See
    taidi_core.models.TaidiSessionFacts for why these are counters."""

    hands_played: int = 0
    hands_won: int = 0
    profit_hands: int = 0
    dealer_hands: int = 0
    dealer_wins: int = 0
    # How the player's own wins came about.
    zimo_wins: int = 0
    direct_wins: int = 0
    bao_wins: int = 0
    # Hands someone else won and the player paid into — the denominator for
    # shooting rate — and how many of those the player shot (discarded the
    # winning tile, i.e. was the sole payer of a `direct` win).
    lost_hands: int = 0
    shot_hands: int = 0
    # Declarations the player made, concealed variants counted separately.
    yao_count: int = 0
    anyao_count: int = 0
    gang_count: int = 0
    angang_count: int = 0
    # Running totals so average tai survives being summed across a filtered
    # set of sessions.
    tai_total: int = 0
    tai_wins: int = 0
    best_hand_cents: int | None = None
    worst_hand_cents: int | None = None
