"""Lifetime and round-level stats derived from ended rooms."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from taidi_core import machine
from taidi_core.models import GameRules, RoomState
from taidi_core.stats import player_lifetime_stats, taidi_round_stats


def _ended_room(now, winner_delta=100):
    A, B = uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="Alice", now=now)
    state = machine.fold(
        state,
        machine.join_player(
            state, expected_seq=state.seq, player_id=B, display_name="Bob", now=now
        ),
    )
    state = machine.fold(
        state,
        machine.start_game(
            state,
            expected_seq=state.seq,
            actor=A,
            rules=GameRules(card_value_cents=winner_delta),
            now=now,
        ),
    )
    state = machine.fold(state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now))
    state = machine.fold(
        state, machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=1, now=now)
    )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))
    return state, A, B


def test_stats_ignore_unended_rooms(now):
    state, A, B = _ended_room(now)
    lobby_only = RoomState.new(room_id=uuid4(), host_id=uuid4(), host_display_name="X", now=now)
    stats = player_lifetime_stats([state, lobby_only])
    assert set(stats) == {A, B}


def test_stats_accumulate_across_games(now):
    room1, A, B = _ended_room(now, winner_delta=100)
    stats = player_lifetime_stats([room1, room1])
    assert stats[A].games == 2
    assert stats[A].wins == 2
    assert stats[B].losses == 2
    assert stats[A].total_cents == room1.balances[A] * 2
    assert stats[A].avg_cents == room1.balances[A]


def test_win_loss_tie_classification(now):
    state, A, B = _ended_room(now)
    stats = player_lifetime_stats([state])
    assert stats[A].wins == 1 and stats[A].losses == 0 and stats[A].ties == 0
    assert stats[B].losses == 1


def _three_player_room(now, rules: GameRules) -> tuple[RoomState, tuple]:
    """A, B, C each win exactly one of three rounds, in that order, and each
    pays a different card count as a loser — designed to land in a known
    double/triple band per rules.double_threshold/triple_threshold."""
    A, B, C = uuid4(), uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    for pid, name in [(B, "B"), (C, "C")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    state = machine.fold(
        state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
    )

    def _play_round(state, winner, others: dict):
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=winner, now=now)
        )
        for pid, cards in others.items():
            state = machine.fold(
                state,
                machine.submit_cards(
                    state, expected_seq=state.seq, actor=pid, cards=cards, now=now
                ),
            )
        return state

    # (The winner always gets an implicit 0-card count from the engine, so
    # no explicit loser card count below may be 0 — that would collide.)
    # Round 1: A wins. B=5 cards (triple, threshold 5), C=2 cards (below double, threshold 3).
    state = _play_round(state, A, {B: 5, C: 2})
    # Round 2: B wins. A=3 cards (double), C=1 card (below double).
    state = _play_round(state, B, {A: 3, C: 1})
    # Round 3: C wins. A=1 card, B=2 cards (both below double).
    state = _play_round(state, C, {A: 1, B: 2})

    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))
    return state, (A, B, C)


def test_round_win_rate_and_payer_rounds(now):
    rules = GameRules(
        card_value_cents=100, double_threshold=3, triple_threshold=5, difference_payouts=False
    )
    state, (A, B, C) = _three_player_room(now, rules)
    stats = taidi_round_stats([state])

    for pid in (A, B, C):
        assert stats[pid].rounds_played == 3
        assert stats[pid].round_wins == 1
        assert stats[pid].round_win_rate == 1 / 3
        # Each won exactly the round they profited on (no specials, no
        # difference payouts in this fixture — profit tracks the win 1:1).
        assert stats[pid].profit_rounds == 1
        assert stats[pid].profit_rate == 1 / 3


def test_double_and_triple_rate_use_payer_rounds_as_denominator(now):
    rules = GameRules(
        card_value_cents=100, double_threshold=3, triple_threshold=5, difference_payouts=False
    )
    state, (A, B, C) = _three_player_room(now, rules)
    stats = taidi_round_stats([state])

    # A: payer in rounds 2 (3 cards -> double) and 3 (1 card -> neither).
    assert stats[A].payer_rounds == 2
    assert stats[A].double_rounds == 1
    assert stats[A].triple_rounds == 0
    assert stats[A].double_rate == 0.5
    assert stats[A].triple_rate == 0.0

    # B: payer in rounds 1 (5 cards -> triple) and 3 (1 card -> neither).
    assert stats[B].payer_rounds == 2
    assert stats[B].double_rounds == 0
    assert stats[B].triple_rounds == 1
    assert stats[B].triple_rate == 0.5

    # C: payer in rounds 1 (2 cards) and 2 (0 cards) — neither band.
    assert stats[C].payer_rounds == 2
    assert stats[C].double_rounds == 0
    assert stats[C].triple_rounds == 0
    assert stats[C].double_rate == 0.0
    assert stats[C].triple_rate == 0.0


def test_special_hand_lets_a_non_winner_profit_without_a_round_win(now):
    """B claims a special hand worth more than B's round loss — B profits
    this round despite A being the round's winner, proving profit_rate and
    round_win_rate are genuinely different metrics, not aliases."""
    A, B = uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    state = machine.fold(
        state,
        machine.join_player(state, expected_seq=state.seq, player_id=B, display_name="B", now=now),
    )
    rules = GameRules(card_value_cents=20, base_cards=2, special_hand_cards=5)
    state = machine.fold(
        state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
    )
    state = machine.fold(
        state, machine.add_special_hand(state, expected_seq=state.seq, actor=B, now=now)
    )
    state = machine.fold(state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now))
    state = machine.fold(
        state, machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=1, now=now)
    )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))

    stats = taidi_round_stats([state])
    assert stats[B].round_wins == 0
    assert stats[B].round_win_rate == 0.0
    assert stats[B].profit_rounds == 1
    assert stats[B].profit_rate == 1.0
    assert stats[B].special_hands_claimed == 1


def test_dangling_playing_round_only_counts_special_claims(now):
    """A special hand is claimed but nobody has claimed the win yet, and the
    host ends the game there — the round stays PLAYING (is_empty requires
    BOTH phase==PLAYING and no transfers; a special claim means transfers
    is non-empty, so it survives the end-of-game pop) with no
    rules_snapshot. special_hands_claimed still counts it;
    rounds_played/round_wins/profit do not. (A COLLECTING-phase dangling
    round — win claimed, cards not fully submitted — is a different case
    that end_game itself blocks: "void it before ending the game.")"""
    A, B = uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    state = machine.fold(
        state,
        machine.join_player(state, expected_seq=state.seq, player_id=B, display_name="B", now=now),
    )
    state = machine.fold(
        state,
        machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
    )
    state = machine.fold(
        state, machine.add_special_hand(state, expected_seq=state.seq, actor=B, now=now)
    )
    # No claim_win — the round stays PLAYING.
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))

    assert state.rounds[-1].phase.value == "playing"  # survived the is_empty pop
    assert state.rounds[-1].rules_snapshot is None
    stats = taidi_round_stats([state])
    assert stats[B].special_hands_claimed == 1
    assert stats[B].rounds_played == 0
    assert stats[B].round_wins == 0


@st.composite
def _round_sequence(draw):
    n_rounds = draw(st.integers(min_value=1, max_value=8))
    double_threshold = draw(st.integers(min_value=1, max_value=10))
    triple_threshold = draw(
        st.integers(min_value=double_threshold, max_value=double_threshold + 10)
    )
    rounds = []
    for _ in range(n_rounds):
        winner = draw(st.integers(0, 2))
        # min_value=1: the engine infers the winner from whoever ends the
        # round with 0 cards, so a loser submitting 0 would collide with it.
        cards = {
            other: draw(st.integers(1, triple_threshold + 5))
            for other in range(3)
            if other != winner
        }
        rounds.append({"winner": winner, "cards": cards})
    return double_threshold, triple_threshold, rounds


_PROPERTY_TEST_NOW = datetime(2026, 9, 1, 20, 0, 0, tzinfo=UTC)


@given(data=_round_sequence())
@settings(max_examples=50)
def test_round_stats_invariants_hold_for_random_games(data):
    now = _PROPERTY_TEST_NOW
    double_threshold, triple_threshold, rounds = data
    A, B, C = uuid4(), uuid4(), uuid4()
    ids = [A, B, C]
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    for pid, name in [(B, "B"), (C, "C")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    rules = GameRules(
        card_value_cents=10,
        double_threshold=double_threshold,
        triple_threshold=triple_threshold,
        difference_payouts=True,
    )
    state = machine.fold(
        state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
    )
    for r in rounds:
        winner = ids[r["winner"]]
        others = {ids[i]: cards for i, cards in r["cards"].items()}
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=winner, now=now)
        )
        for pid, cards in others.items():
            state = machine.fold(
                state,
                machine.submit_cards(
                    state, expected_seq=state.seq, actor=pid, cards=cards, now=now
                ),
            )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))

    stats = taidi_round_stats([state])
    resolved_rounds = len(rounds)
    total_wins = 0
    for pid in ids:
        s = stats[pid]
        assert s.rounds_played == resolved_rounds
        assert s.round_wins + s.payer_rounds == s.rounds_played
        total_wins += s.round_wins
        assert math.isclose(s.round_win_rate * s.rounds_played, s.round_wins, abs_tol=1e-9)
        assert math.isclose(s.profit_rate * s.rounds_played, s.profit_rounds, abs_tol=1e-9)
        if s.payer_rounds:
            assert s.double_rounds + s.triple_rounds <= s.payer_rounds
            assert 0.0 <= s.double_rate <= 1.0
            assert 0.0 <= s.triple_rate <= 1.0
    assert total_wins == resolved_rounds
