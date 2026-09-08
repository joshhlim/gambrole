"""Lifetime and hand-level stats derived from ended Mahjong rooms."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st
from mahjong_core import machine
from mahjong_core.models import MahjongRules, RoomState, TaiPayout
from mahjong_core.stats import mahjong_hand_stats, player_lifetime_stats


def _ended_room(now, yao_delta=100):
    A, B, C, D = uuid4(), uuid4(), uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="Alice", now=now)
    for pid, name in [(B, "Bob"), (C, "Cara"), (D, "Dan")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    state = machine.fold(
        state,
        machine.start_game(
            state,
            expected_seq=state.seq,
            actor=A,
            rules=MahjongRules(yao_chips=yao_delta),
            now=now,
        ),
    )
    state = machine.fold(
        state,
        machine.declare_yao(
            state, expected_seq=state.seq, actor=A, target_seat=1, an=False, now=now
        ),
    )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))
    return state, A, B, C, D


def test_stats_ignore_unended_rooms(now):
    state, A, B, C, D = _ended_room(now)
    lobby_only = RoomState.new(room_id=uuid4(), host_id=uuid4(), host_display_name="X", now=now)
    stats = player_lifetime_stats([state, lobby_only])
    assert set(stats) == {A, B, C, D}


def test_stats_accumulate_across_games(now):
    room1, A, B, C, D = _ended_room(now, yao_delta=100)
    stats = player_lifetime_stats([room1, room1])
    assert stats[A].games == 2
    assert stats[A].wins == 2
    assert stats[B].losses == 2
    assert stats[A].total_cents == room1.balances[A] * 2
    assert stats[A].avg_cents == room1.balances[A]


def test_win_loss_tie_classification(now):
    state, A, B, C, D = _ended_room(now)
    stats = player_lifetime_stats([state])
    assert stats[A].wins == 1 and stats[A].losses == 0 and stats[A].ties == 0
    assert stats[B].losses == 1
    assert stats[C].ties == 1 and stats[D].ties == 1


def _clean_tai_rules(**overrides) -> MahjongRules:
    """Round, easy-to-check payouts — not a real preset, just clean numbers
    for testing the hand-stats aggregation mechanism itself."""
    table = {1: TaiPayout(hu=100, zimo=50), 2: TaiPayout(hu=200, zimo=100)}
    return MahjongRules(max_tai=2, tai_table=table, gang_chips=10, **overrides)


def _four_hand_room(now) -> tuple[RoomState, tuple]:
    """Seats: A=0 (dealer to start), B=1, C=2, D=3.

    Hand 1: A (dealer) HUs direct off B at 1 tai -> A wins as dealer, so the
      dealer stays A for hand 2 (win-driven rotation: gang is irrelevant to
      a win, only whether the dealer themselves won).
    Hand 2: B HUs zimo at 2 tai -> non-dealer win, dealer rotates to B.
    Hand 3: C GANGs on D (an "other" gang), then C HUs direct off D at 1 tai
      -> non-dealer win (dealer is B), dealer rotates to C.
    Hand 4: no winner declared, no gang -> dealer stays C.
    """
    A, B, C, D = uuid4(), uuid4(), uuid4(), uuid4()
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    for pid, name in [(B, "B"), (C, "C"), (D, "D")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    state = machine.fold(
        state,
        machine.start_game(
            state, expected_seq=state.seq, actor=A, rules=_clean_tai_rules(), now=now
        ),
    )

    state = machine.fold(
        state,
        machine.declare_hu(
            state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=1, now=now
        ),
    )
    state = machine.fold(
        state,
        machine.declare_hu(
            state,
            expected_seq=state.seq,
            actor=B,
            mode="zimo",
            target_seat=None,
            tai=2,
            now=now,
        ),
    )
    state = machine.fold(
        state,
        machine.declare_gang(state, expected_seq=state.seq, actor=C, target=3, now=now),
    )
    state = machine.fold(
        state,
        machine.declare_hu(
            state, expected_seq=state.seq, actor=C, mode="direct", target_seat=3, tai=1, now=now
        ),
    )
    state = machine.fold(
        state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
    )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))
    return state, (A, B, C, D)


def test_hu_rate_and_win_mode_breakdown(now):
    state, (A, B, C, D) = _four_hand_room(now)
    stats = mahjong_hand_stats([state])

    for pid in (A, B, C, D):
        assert stats[pid].hands_played == 4

    assert stats[A].hu_count == 1 and stats[A].hu_rate == 0.25
    assert stats[A].win_mode_counts == {"direct": 1}
    assert stats[A].win_mode_rates == {"direct": 1.0}
    assert stats[A].tai_distribution == {1: 1}
    assert stats[A].avg_tai_on_wins == 1.0

    assert stats[B].hu_count == 1
    assert stats[B].win_mode_counts == {"zimo": 1}
    assert stats[B].tai_distribution == {2: 1}
    assert stats[B].avg_tai_on_wins == 2.0

    assert stats[C].hu_count == 1
    assert stats[C].win_mode_counts == {"direct": 1}

    assert stats[D].hu_count == 0
    assert stats[D].hu_rate == 0.0
    assert stats[D].win_mode_counts == {}
    assert stats[D].avg_tai_on_wins == 0.0


def test_dealer_win_rate(now):
    state, (A, B, C, D) = _four_hand_room(now)
    stats = mahjong_hand_stats([state])

    # A dealt hands 1-2 (won hand 1), B dealt hand 3, C dealt hand 4.
    assert stats[A].dealer_hands == 2
    assert stats[A].dealer_wins == 1
    assert stats[A].dealer_win_rate == 0.5

    assert stats[B].dealer_hands == 1
    assert stats[B].dealer_wins == 0
    assert stats[B].dealer_win_rate == 0.0

    assert stats[C].dealer_hands == 1
    assert stats[C].dealer_wins == 0

    assert stats[D].dealer_hands == 0
    assert stats[D].dealer_win_rate == 0.0


def test_profit_by_kind_and_best_worst_hand(now):
    state, (A, B, C, D) = _four_hand_room(now)
    stats = mahjong_hand_stats([state])

    # Hand 1: B pays A 100 (HU). Hand 2: A, C, D each pay B 100 (HU, zimo).
    # Hand 3: D pays C 30 (GANG), then D pays C 100 (HU). Hand 4: no transfers.
    assert stats[A].profit_by_kind == {"hu": 0}  # +100 (hand1) - 100 (hand2)
    assert stats[A].best_hand_chips == 100
    assert stats[A].worst_hand_chips == -100

    assert stats[B].profit_by_kind == {"hu": 200}  # -100 (hand1) + 300 (hand2)
    assert stats[B].best_hand_chips == 300
    assert stats[B].worst_hand_chips == -100

    assert stats[C].profit_by_kind == {"hu": 0, "gang": 30}  # -100 (hand2) + 30 + 100 (hand3)
    assert stats[C].best_hand_chips == 130
    assert stats[C].worst_hand_chips == -100

    assert stats[D].profit_by_kind == {"hu": -200, "gang": -30}
    assert stats[D].best_hand_chips == 0
    assert stats[D].worst_hand_chips == -130


_PROPERTY_TEST_NOW = datetime(2026, 9, 1, 20, 0, 0, tzinfo=UTC)


@st.composite
def _hand_sequence(draw):
    """A sequence of hands, each either a HU (by a random actor, mode, and
    tai) or a no-win — enough to exercise the aggregation across a mix of
    outcomes without needing to model the dealer/wind rotation (irrelevant
    to what's being checked here)."""
    n_hands = draw(st.integers(min_value=1, max_value=6))
    hands = []
    for _ in range(n_hands):
        if draw(st.booleans()):
            actor = draw(st.integers(0, 3))
            mode = draw(st.sampled_from(["direct", "zimo"]))
            tai = draw(st.integers(1, 2))
            if mode == "direct":
                target = draw(st.sampled_from([s for s in range(4) if s != actor]))
            else:
                target = None
            hands.append({"kind": "hu", "actor": actor, "mode": mode, "tai": tai, "target": target})
        else:
            hands.append({"kind": "no_win"})
    return hands


@given(hands=_hand_sequence())
@settings(max_examples=50)
def test_hand_stats_invariants_hold_for_random_games(hands):
    now = _PROPERTY_TEST_NOW
    A, B, C, D = uuid4(), uuid4(), uuid4(), uuid4()
    ids = [A, B, C, D]
    state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    for pid, name in [(B, "B"), (C, "C"), (D, "D")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    state = machine.fold(
        state,
        machine.start_game(
            state, expected_seq=state.seq, actor=A, rules=_clean_tai_rules(), now=now
        ),
    )
    for h in hands:
        actor = ids[h["actor"]] if h["kind"] == "hu" else A
        if h["kind"] == "hu":
            state = machine.fold(
                state,
                machine.declare_hu(
                    state,
                    expected_seq=state.seq,
                    actor=actor,
                    mode=h["mode"],
                    target_seat=h["target"],
                    tai=h["tai"],
                    now=now,
                ),
            )
        else:
            state = machine.fold(
                state, machine.declare_no_win(state, expected_seq=state.seq, actor=actor, now=now)
            )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))

    stats = mahjong_hand_stats([state])
    closed_hands = len(hands)
    for pid in ids:
        s = stats[pid]
        assert s.hands_played == closed_hands
        assert sum(s.win_mode_counts.values()) == s.hu_count
        assert sum(s.tai_distribution.values()) == s.hu_count
        if s.hu_count:
            assert 0.0 <= s.hu_rate <= 1.0
        # profit_by_kind sums to the same total balance the room-level
        # lifetime stats independently compute from room.balances.
        assert sum(s.profit_by_kind.values()) == s.lifetime.total_cents
