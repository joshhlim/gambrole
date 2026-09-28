"""Taidi engine edge cases found in the 2026-09-28 audit: undoing specials
after someone stepped out, voiding around special hands, seat bookkeeping
after a lobby leave, and input bounds."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from taidi_core import machine
from taidi_core.errors import IllegalTransition, NotAuthorized
from taidi_core.models import GameRules, RoomState, RoundPhase
from taidi_core.stats import player_lifetime_stats


def _room(now, n=3, rules=None):
    ids = [uuid4() for _ in range(n)]
    state = RoomState.new(room_id=uuid4(), host_id=ids[0], host_display_name="P0", now=now)
    for i, pid in enumerate(ids[1:], start=1):
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=f"P{i}", now=now
            ),
        )
    state = machine.fold(
        state,
        machine.start_game(
            state, expected_seq=state.seq, actor=ids[0], rules=rules or GameRules(), now=now
        ),
    )
    return state, ids


def _do(state, command, **kwargs):
    return machine.fold(state, command(state, expected_seq=state.seq, **kwargs))


def _round(state, now, winner, cards: dict):
    state = _do(state, machine.claim_win, actor=winner, now=now)
    for pid, n in cards.items():
        state = _do(state, machine.submit_cards, actor=pid, cards=n, now=now)
    return state


class TestUndoSpecialAfterStepOut:
    def test_undo_reverses_exactly_the_last_claim(self, now):
        rules = GameRules(card_value_cents=100, special_hand_cards=1)
        state, (A, B, C, D, E) = _room(now, 5, rules)
        state = _do(state, machine.add_special_hand, actor=A, now=now)  # 4 payers
        state = _do(state, machine.step_out, actor=D, now=now)
        state = _do(state, machine.step_out, actor=E, now=now)
        after_first = dict(state.balances)
        state = _do(state, machine.add_special_hand, actor=A, now=now)  # 2 payers
        state = _do(state, machine.void_special_hand, actor=A, now=now)
        assert state.balances == after_first
        assert state.rounds[-1].special_counts[A] == 1
        assert len([t for t in state.rounds[-1].transfers if t.to_player == A]) == 4


class TestVoidTargeting:
    def test_special_in_the_new_round_doesnt_block_undoing_the_last_one(self, now):
        state, (A, B, C) = _room(now)
        start = dict(state.balances)
        state = _round(state, now, A, {B: 3, C: 5})
        state = _do(state, machine.add_special_hand, actor=B, now=now)
        after_special_only = {
            pid: start[pid]
            + sum(
                (t.amount_cents if t.to_player == pid else -t.amount_cents)
                for t in state.rounds[-1].transfers
                if pid in (t.from_player, t.to_player)
            )
            for pid in start
        }
        state = _do(state, machine.void_last_round, actor=A, now=now)
        # Round 1's card settlement is gone; round 2's special survives.
        assert len(state.rounds) == 1
        assert state.rounds[0].phase == RoundPhase.PLAYING
        assert state.rounds[0].special_counts[B] == 1
        assert state.balances == after_special_only
        assert sum(state.balances.values()) == 0

    def test_player_who_stepped_out_cant_void(self, now):
        state, (A, B, C) = _room(now)
        state = _round(state, now, B, {A: 3, C: 5})
        state = _do(state, machine.step_out, actor=B, now=now)
        with pytest.raises(NotAuthorized):
            machine.void_last_round(state, expected_seq=state.seq, actor=B, now=now)


class TestSeatsAfterLobbyLeave:
    def test_rejoin_takes_the_vacated_seat(self, now):
        ids = [uuid4() for _ in range(4)]
        A, B, C, D = ids
        state = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
        for pid in (B, C):
            state = _do(state, machine.join_player, player_id=pid, display_name="x", now=now)
        state = _do(state, machine.leave_room, actor=B, now=now)
        state = _do(state, machine.join_player, player_id=D, display_name="x", now=now)
        assert sorted(m.seat for m in state.members.values()) == [0, 1, 2]


class TestBounds:
    def test_card_count_above_a_deck_is_rejected(self, now):
        state, (A, B, C) = _room(now)
        state = _do(state, machine.claim_win, actor=A, now=now)
        with pytest.raises(IllegalTransition):
            machine.submit_cards(state, expected_seq=state.seq, actor=B, cards=53, now=now)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"card_value_cents": 10_001},
            {"double_threshold": 0},
            {"base_cards": 53},
            {"special_hand_cards": -1},
        ],
    )
    def test_rules_out_of_range_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            GameRules(**kwargs)


def test_stats_name_players_who_stepped_out(now):
    state, (A, B, C) = _room(now)
    state = _round(state, now, A, {B: 3, C: 5})
    state = _do(state, machine.step_out, actor=B, now=now)
    state = _do(state, machine.end_game, actor=A, now=now)
    assert player_lifetime_stats([state])[B].display_name == "P1"


def test_a_game_started_under_looser_rules_still_replays(now):
    """Limits on rules apply when a game starts, not when an old game is
    loaded again — otherwise tightening one would break every older game."""
    A, B = uuid4(), uuid4()
    lobby = RoomState.new(room_id=uuid4(), host_id=A, host_display_name="A", now=now)
    lobby = _do(lobby, machine.join_player, player_id=B, display_name="B", now=now)
    [start] = machine.start_game(lobby, expected_seq=lobby.seq, actor=A, rules=GameRules(), now=now)
    loose = {**GameRules().model_dump(mode="json"), "card_value_cents": 50_000}
    replayed = machine.fold(lobby, [start.model_copy(update={"payload": {"rules": loose}})])
    assert replayed.rules is not None and replayed.rules.card_value_cents == 50_000
