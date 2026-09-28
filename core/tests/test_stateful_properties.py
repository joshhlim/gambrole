"""Random whole-game simulations through both engines.

The other property tests check the scoring math in isolation; these check
what only shows up across many commands in a row — specials, voids,
step-outs, seat swaps, wind decisions — by asserting after every accepted
command that money still sums to zero and seats are unique, and at the end
of each game that replaying the event log from scratch gives the same state
as applying it live.

Commands are drawn with realistic weights (claiming and settling rounds
dominate, as at a real table) so most examples get deep into a game rather
than dying in the lobby.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from mahjong_core import machine as mj
from mahjong_core.models import MahjongRules
from mahjong_core.models import RoomState as MjState
from taidi_core import machine as td
from taidi_core.errors import MachineError
from taidi_core.models import GameRules, RoundPhase, TransferKind
from taidi_core.models import RoomState as TdState
from taidi_core.rules import compute_card_transfers

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)
PLAYERS = [uuid4() for _ in range(5)]


class Sim:
    def __init__(self, engine: Any, initial: Any, rng: random.Random):
        self.engine, self.initial, self.rng = engine, initial, rng
        self.state, self.log = initial, []
        self.accepted: list[str] = []

    def step(self, name: str, **kwargs: Any) -> None:
        try:
            events = getattr(self.engine, name)(
                self.state, expected_seq=self.state.seq, now=NOW, **kwargs
            )
        except MachineError:
            return
        self.state = self.engine.fold(self.state, events)
        self.log.extend(events)
        self.accepted.append(name)
        assert sum(self.state.balances.values()) == 0
        seats = [m.seat for m in self.state.members.values()]
        assert len(seats) == len(set(seats))

    def assert_replays(self) -> None:
        """Checked once per game rather than per step: live application and
        replay can only diverge in a way that persists to the end."""
        assert self.engine.fold(self.initial, self.log) == self.state

    def player(self) -> UUID:
        return self.rng.choice(PLAYERS)

    def lobby(self, table_size: int) -> None:
        for _ in range(self.rng.randint(0, 8)):
            if self.rng.random() < 0.6:
                self.step("join_player", player_id=self.player(), display_name="p")
            else:
                self.step("leave_room", actor=self.player())
        for pid in PLAYERS:
            if len(self.state.members) >= table_size:
                break
            self.step("join_player", player_id=pid, display_name="p")


def _taidi_turn(sim: Sim) -> None:
    s, rng = sim.state, sim.rng
    round_ = s.current_round
    roll = rng.random()
    if roll < 0.30:
        sim.step("claim_win", actor=sim.player())
    elif roll < 0.60 and round_ is not None and round_.winner is not None:
        for pid in list(s.members):
            if pid != round_.winner and pid not in round_.cards_submitted:
                sim.step("submit_cards", actor=pid, cards=rng.randint(1, 13))
    elif roll < 0.72:
        sim.step("add_special_hand", actor=sim.player())
    elif roll < 0.80:
        sim.step("void_special_hand", actor=sim.player())
    elif roll < 0.88:
        sim.step("void_last_round", actor=rng.choice([s.host_id, sim.player()]))
    elif roll < 0.94:
        sim.step("step_out", actor=sim.player())
    elif roll < 0.97:
        sim.step("submit_cards", actor=sim.player(), cards=rng.randint(1, 13))
    else:
        sim.step("end_game", actor=s.host_id)


def _mahjong_turn(sim: Sim) -> None:
    s, rng = sim.state, sim.rng
    seat = rng.randint(0, 3)
    roll = rng.random()
    if roll < 0.20:
        sim.step("declare_yao", actor=sim.player(), target_seat=seat, an=rng.random() < 0.3)
    elif roll < 0.35:
        sim.step("declare_gang", actor=sim.player(), target=rng.choice([seat, "angang"]))
    elif roll < 0.65:
        sim.step(
            "declare_hu",
            actor=sim.player(),
            mode=rng.choice(["direct", "zimo", "bao"]),
            target_seat=seat,
            tai=rng.randint(1, 5),
            zimo_bonus=rng.random() < 0.3,
            klppdd=rng.random() < 0.3,
        )
    elif roll < 0.90:
        sim.step("declare_no_win", actor=sim.player())
    elif roll < 0.98:
        sim.step("continue_wind", actor=s.host_id)
    else:
        sim.step("end_game", actor=s.host_id)


_settings = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@_settings
@given(st.randoms(use_true_random=False), st.integers(min_value=2, max_value=5))
def test_taidi_random_games_keep_invariants(rng, table_size):
    initial = TdState.new(room_id=uuid4(), host_id=PLAYERS[0], host_display_name="h", now=NOW)
    sim = Sim(td, initial, rng)
    sim.lobby(table_size)
    sim.step("start_game", actor=sim.state.host_id, rules=GameRules())
    for _ in range(rng.randint(0, 80)):
        _taidi_turn(sim)
    sim.assert_replays()

    # ADR-0001's replay guarantee: every resolved round's cached card
    # transfers are exactly what the scoring engine computes from the
    # round's own counts and rules snapshot.
    for round_ in sim.state.rounds:
        if round_.phase != RoundPhase.RESOLVED:
            continue
        assert round_.winner is not None and round_.rules_snapshot is not None
        recomputed, _ = compute_card_transfers(
            {round_.winner: 0, **round_.cards_submitted}, round_.rules_snapshot, round_.round_no
        )
        cached = [t for t in round_.transfers if t.kind != TransferKind.SPECIAL]
        assert cached == recomputed


@_settings
@given(st.randoms(use_true_random=False))
def test_mahjong_random_games_keep_invariants(rng):
    initial = MjState.new(room_id=uuid4(), host_id=PLAYERS[0], host_display_name="h", now=NOW)
    sim = Sim(mj, initial, rng)
    sim.lobby(4)
    if rng.random() < 0.5:
        swap = rng.sample(sorted(sim.state.members, key=str), k=2)
        sim.step(
            "assign_seats",
            actor=sim.state.host_id,
            seat_map={
                swap[0]: sim.state.members[swap[1]].seat,
                swap[1]: sim.state.members[swap[0]].seat,
            },
        )
    sim.step("start_game", actor=sim.state.host_id, rules=MahjongRules())
    for _ in range(rng.randint(0, 120)):
        _mahjong_turn(sim)
    sim.assert_replays()
