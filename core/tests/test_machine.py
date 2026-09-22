"""The room/round state machine: legal transitions, illegal ones, and a full game."""

from __future__ import annotations

from uuid import uuid4

import pytest
from taidi_core import machine
from taidi_core.errors import IllegalTransition, NotAuthorized, SeqConflict
from taidi_core.models import GameRules, RoomState, RoomStatus, RoundPhase


def _room(now, n_players=3):
    ids = [uuid4() for _ in range(n_players)]
    host = ids[0]
    state = RoomState.new(room_id=uuid4(), host_id=host, host_display_name="P0", now=now)
    for i, pid in enumerate(ids[1:], start=1):
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=f"P{i}", now=now
            ),
        )
    return state, ids


def _play_round(state, now, winner, others: dict):
    """others: {player_id: cards}. Drives claim_win + submit_cards to resolution."""
    state = machine.fold(
        state, machine.claim_win(state, expected_seq=state.seq, actor=winner, now=now)
    )
    for pid, cards in others.items():
        state = machine.fold(
            state,
            machine.submit_cards(state, expected_seq=state.seq, actor=pid, cards=cards, now=now),
        )
    return state


class TestLobby:
    def test_join_then_start(self, now):
        state, (A, B, C) = _room(now)
        assert state.status == RoomStatus.LOBBY
        assert len(state.members) == 3

        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        assert state.status == RoomStatus.IN_PROGRESS
        assert state.rounds[0].round_no == 1
        assert state.rounds[0].phase == RoundPhase.PLAYING

    def test_cannot_join_after_start(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        with pytest.raises(IllegalTransition):
            machine.join_player(
                state, expected_seq=state.seq, player_id=uuid4(), display_name="Late", now=now
            )

    def test_only_host_can_start(self, now):
        state, (A, B, C) = _room(now)
        with pytest.raises(NotAuthorized):
            machine.start_game(state, expected_seq=state.seq, actor=B, rules=GameRules(), now=now)

    def test_cannot_start_alone(self, now):
        state = RoomState.new(room_id=uuid4(), host_id=uuid4(), host_display_name="Solo", now=now)
        with pytest.raises(IllegalTransition):
            machine.start_game(
                state, expected_seq=state.seq, actor=state.host_id, rules=GameRules(), now=now
            )

    def test_stale_seq_rejected(self, now):
        state, (A, B, C) = _room(now)
        with pytest.raises(SeqConflict):
            machine.start_game(
                state, expected_seq=state.seq + 5, actor=A, rules=GameRules(), now=now
            )


class TestLeaveDisband:
    def test_member_can_leave_lobby(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state, machine.leave_room(state, expected_seq=state.seq, actor=B, now=now)
        )
        assert set(state.members) == {A, C}
        assert B not in state.balances

    def test_non_member_cannot_leave(self, now):
        state, (A, B, C) = _room(now)
        with pytest.raises(NotAuthorized):
            machine.leave_room(state, expected_seq=state.seq, actor=uuid4(), now=now)

    def test_host_cannot_leave(self, now):
        state, (A, B, C) = _room(now)
        with pytest.raises(IllegalTransition):
            machine.leave_room(state, expected_seq=state.seq, actor=A, now=now)

    def test_cannot_leave_after_start(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        with pytest.raises(IllegalTransition):
            machine.leave_room(state, expected_seq=state.seq, actor=B, now=now)

    def test_host_can_disband_lobby(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state, machine.disband_room(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.status == RoomStatus.DISBANDED
        assert state.ended_at == now

    def test_non_host_cannot_disband(self, now):
        state, (A, B, C) = _room(now)
        with pytest.raises(NotAuthorized):
            machine.disband_room(state, expected_seq=state.seq, actor=B, now=now)

    def test_cannot_disband_after_start(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        with pytest.raises(IllegalTransition):
            machine.disband_room(state, expected_seq=state.seq, actor=A, now=now)


class TestRound:
    def test_second_win_claim_rejected(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        with pytest.raises(IllegalTransition, match="already claimed"):
            machine.claim_win(state, expected_seq=state.seq, actor=B, now=now)

    def test_winner_cannot_submit_cards(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        with pytest.raises(IllegalTransition):
            machine.submit_cards(state, expected_seq=state.seq, actor=A, cards=0, now=now)

    def test_double_submit_rejected(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        state = machine.fold(
            state, machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=3, now=now)
        )
        with pytest.raises(IllegalTransition, match="already submitted"):
            machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=99, now=now)

    def test_round_resolves_when_last_card_count_lands(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        assert state.rounds[0].phase == RoundPhase.RESOLVED
        assert len(state.rounds) == 2
        assert state.rounds[1].phase == RoundPhase.PLAYING
        assert sum(state.balances.values()) == 0

    def test_host_can_submit_for_another_player(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        state = machine.fold(
            state,
            machine.submit_for(
                state, expected_seq=state.seq, actor=A, target_player=B, cards=3, now=now
            ),
        )
        assert state.rounds[0].cards_submitted[B] == 3

    def test_non_host_cannot_submit_for_another(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        with pytest.raises(NotAuthorized):
            machine.submit_for(
                state, expected_seq=state.seq, actor=B, target_player=C, cards=3, now=now
            )


class TestSpecialHands:
    def test_special_hand_settles_immediately(self, now):
        state, (A, B, C) = _room(now)
        rules = GameRules(card_value_cents=100, special_hand_cards=5)
        state = machine.fold(
            state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
        )
        before = dict(state.balances)
        state = machine.fold(
            state, machine.add_special_hand(state, expected_seq=state.seq, actor=B, now=now)
        )
        assert state.balances[B] == before[B] + 500 * 2  # A and C each pay B
        assert state.balances[A] == before[A] - 500
        assert state.balances[C] == before[C] - 500
        assert sum(state.balances.values()) == 0
        assert state.rounds[0].phase == RoundPhase.PLAYING  # doesn't affect round phase

    def test_disabled_special_hands_rejected(self, now):
        state, (A, B, C) = _room(now)
        rules = GameRules(special_hands_enabled=False)
        state = machine.fold(
            state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
        )
        with pytest.raises(IllegalTransition):
            machine.add_special_hand(state, expected_seq=state.seq, actor=A, now=now)

    def test_special_hand_allowed_during_collecting(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        state = machine.fold(
            state, machine.add_special_hand(state, expected_seq=state.seq, actor=C, now=now)
        )
        assert state.rounds[0].special_counts[C] == 1


class TestVoid:
    def test_void_resolved_round_reverts_balances(self, now):
        state, (A, B, C) = _room(now)
        rules = GameRules(card_value_cents=100)
        state = machine.fold(
            state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
        )
        before = dict(state.balances)
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        state = machine.fold(
            state, machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.balances == before
        assert len(state.rounds) == 1
        assert state.rounds[0].phase == RoundPhase.PLAYING
        assert state.rounds[0].winner is None

    def test_void_preserves_special_hands_claimed_in_that_round(self, now):
        state, (A, B, C) = _room(now)
        rules = GameRules(card_value_cents=100)
        state = machine.fold(
            state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
        )
        state = machine.fold(
            state, machine.add_special_hand(state, expected_seq=state.seq, actor=B, now=now)
        )
        after_special = dict(state.balances)
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        state = machine.fold(
            state, machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.balances == after_special
        assert state.rounds[0].special_counts[B] == 1
        assert sum(state.balances.values()) == 0

    def test_void_collecting_round(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        state = machine.fold(
            state, machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=3, now=now)
        )
        state = machine.fold(
            state, machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.rounds[0].phase == RoundPhase.PLAYING
        assert state.rounds[0].winner is None
        assert state.rounds[0].cards_submitted == {}

    def test_void_targets_last_resolved_round_not_the_fresh_next_one(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        assert len(state.rounds) == 2  # round 1 resolved, empty round 2 created
        state = machine.fold(
            state, machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert len(state.rounds) == 1  # back to just round 1, reopened
        assert state.rounds[0].round_no == 1

    def test_nothing_to_void_at_game_start(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        with pytest.raises(IllegalTransition):
            machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)

    def test_only_host_can_void(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        with pytest.raises(NotAuthorized):
            machine.void_last_round(state, expected_seq=state.seq, actor=B, now=now)


class TestEndGame:
    def test_cannot_end_while_collecting(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        with pytest.raises(IllegalTransition):
            machine.end_game(state, expected_seq=state.seq, actor=A, now=now)

    def test_only_the_host_can_end(self, now):
        """Ending finalises every balance and creates debts, so it takes the
        host — the same bar as starting or disbanding."""
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        with pytest.raises(NotAuthorized):
            machine.end_game(state, expected_seq=state.seq, actor=C, now=now)

        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.status == RoomStatus.ENDED
        assert state.ended_at == now

    def test_trailing_empty_round_is_dropped(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = _play_round(state, now, winner=A, others={B: 3, C: 11})
        assert len(state.rounds) == 2
        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert len(state.rounds) == 1  # the fresh, untouched round 2 is dropped

    def test_no_commands_accepted_after_end(self, now):
        state, (A, B, C) = _room(now)
        state = machine.fold(
            state,
            machine.start_game(state, expected_seq=state.seq, actor=A, rules=GameRules(), now=now),
        )
        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        with pytest.raises(IllegalTransition):
            machine.claim_win(state, expected_seq=state.seq, actor=A, now=now)


def test_full_simulated_game(now):
    """The Phase-1 acceptance bar: the state machine can drive a full game end to end."""
    state, (A, B, C) = _room(now)
    rules = GameRules(card_value_cents=20, base_cards=2, special_hand_cards=5)
    state = machine.fold(
        state, machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now)
    )

    # Round 1: A wins, B=3, C=11
    state = _play_round(state, now, winner=A, others={B: 3, C: 11})
    assert state.rounds[0].winner == A

    # C claims a special hand mid-round-2
    state = machine.fold(
        state, machine.add_special_hand(state, expected_seq=state.seq, actor=C, now=now)
    )

    # Round 2: B wins, A=5, host enters C's cards for them (phone died)
    state = machine.fold(state, machine.claim_win(state, expected_seq=state.seq, actor=B, now=now))
    state = machine.fold(
        state, machine.submit_cards(state, expected_seq=state.seq, actor=A, cards=5, now=now)
    )
    state = machine.fold(
        state,
        machine.submit_for(
            state, expected_seq=state.seq, actor=A, target_player=C, cards=2, now=now
        ),
    )
    assert state.rounds[1].winner == B

    # Host misclicked — undo round 2 and redo it with the right numbers
    state = machine.fold(
        state, machine.void_last_round(state, expected_seq=state.seq, actor=A, now=now)
    )
    state = _play_round(state, now, winner=B, others={A: 6, C: 1})
    assert state.rounds[1].winner == B

    # Round 3: C wins, no cards owed elsewhere
    state = _play_round(state, now, winner=C, others={A: 1, B: 1})

    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))

    assert state.status == RoomStatus.ENDED
    assert sum(state.balances.values()) == 0
    assert [r.phase for r in state.rounds] == [RoundPhase.RESOLVED] * 3
    assert state.rounds[0].engine_version is not None


def test_replay_from_scratch_reproduces_live_state(now):
    """Folding a room's whole event log from an empty state must equal the live-built state."""
    room_id, A, B, C = uuid4(), uuid4(), uuid4(), uuid4()
    rules = GameRules(card_value_cents=50)

    def build(track_all=False):
        state = RoomState.new(room_id=room_id, host_id=A, host_display_name="Alice", now=now)
        all_events = []

        def do(events):
            nonlocal state
            if track_all:
                all_events.extend(events)
            state = machine.fold(state, events)

        do(
            machine.join_player(
                state, expected_seq=state.seq, player_id=B, display_name="Bob", now=now
            )
        )
        do(
            machine.join_player(
                state, expected_seq=state.seq, player_id=C, display_name="Charlie", now=now
            )
        )
        do(machine.start_game(state, expected_seq=state.seq, actor=A, rules=rules, now=now))
        do(machine.claim_win(state, expected_seq=state.seq, actor=A, now=now))
        do(machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=3, now=now))
        do(machine.submit_cards(state, expected_seq=state.seq, actor=C, cards=11, now=now))
        do(machine.add_special_hand(state, expected_seq=state.seq, actor=B, now=now))
        return state, all_events

    live_state, all_events = build(track_all=True)

    replay_start = RoomState.new(room_id=room_id, host_id=A, host_display_name="Alice", now=now)
    replayed = machine.fold(replay_start, all_events)

    assert replayed.balances == live_state.balances
    assert replayed.seq == live_state.seq
    assert replayed.rounds == live_state.rounds
    assert replayed.members == live_state.members
