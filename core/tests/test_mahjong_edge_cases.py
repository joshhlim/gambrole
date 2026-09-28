"""Mahjong engine edge cases found in the 2026-09-28 audit: seat bookkeeping
after a lobby leave, wind prompts past the 4th wind, and actions against an
ended game."""

from __future__ import annotations

import pytest
from mahjong_core import machine
from mahjong_core.models import MahjongRules, RoomState, TaiPayout
from mahjong_core.stats import mahjong_hand_stats
from pydantic import ValidationError
from taidi_core.errors import IllegalTransition

from .conftest import letter_id

A, B, C, D, E = (letter_id(x) for x in "ABCDE")


def _join(state: RoomState, pid, now) -> RoomState:
    return machine.fold(
        state,
        machine.join_player(
            state, expected_seq=state.seq, player_id=pid, display_name="x", now=now
        ),
    )


def _lobby(now, players=(B, C, D)) -> RoomState:
    state = RoomState.new(room_id=letter_id("room"), host_id=A, host_display_name="A", now=now)
    for pid in players:
        state = _join(state, pid, now)
    return state


def _start(state: RoomState, now) -> RoomState:
    return machine.fold(
        state,
        machine.start_game(state, expected_seq=state.seq, actor=A, rules=MahjongRules(), now=now),
    )


def _leave(state: RoomState, pid, now) -> RoomState:
    return machine.fold(
        state, machine.leave_room(state, expected_seq=state.seq, actor=pid, now=now)
    )


class TestSeatsAfterLobbyLeave:
    def test_rejoin_takes_the_vacated_seat(self, now):
        state = _join(_leave(_lobby(now), B, now), E, now)
        assert sorted(m.seat for m in state.members.values()) == [0, 1, 2, 3]
        assert state.members[E].seat == 1

    def test_declaring_against_a_seat_charges_whoever_sits_there(self, now):
        state = _start(_join(_leave(_lobby(now), B, now), E, now), now)
        # C sits in seat 2; a yao against seat 2 must charge C, not anyone else.
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=2, an=False, now=now
            ),
        )
        assert state.balances[C] < 0
        assert state.balances[D] == 0 and state.balances[E] == 0


class TestWindsPastFour:
    def _to_last_seat_of_wind(self, state: RoomState, wind: int, now) -> RoomState:
        # A gang + no-win rotates the dealer one seat per hand.
        while not (state.hands[-1].wind == wind and state.hands[-1].dealer_seat == 3):
            state = machine.fold(
                state,
                machine.declare_gang(
                    state, expected_seq=state.seq, actor=A, target="angang", now=now
                ),
            )
            state = machine.fold(
                state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
            )
        return state

    def _win(self, state: RoomState, now) -> RoomState:
        return machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="zimo",
                target_seat=None,
                tai=1,
                now=now,
            ),
        )

    def test_host_is_asked_again_at_the_end_of_each_extra_wind(self, now):
        state = self._win(self._to_last_seat_of_wind(_start(_lobby(now), now), 4, now), now)
        assert state.pending_wind_decision
        state = machine.fold(
            state, machine.continue_wind(state, expected_seq=state.seq, actor=A, now=now)
        )
        state = self._win(self._to_last_seat_of_wind(state, 5, now), now)
        assert state.pending_wind_decision
        assert state.hands[-1].wind == 5

    def test_continue_wind_refused_after_the_game_ended(self, now):
        state = self._win(self._to_last_seat_of_wind(_start(_lobby(now), now), 4, now), now)
        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert not state.pending_wind_decision
        with pytest.raises(IllegalTransition):
            machine.continue_wind(state, expected_seq=state.seq, actor=A, now=now)


class TestValidation:
    def test_gang_target_must_be_a_seat_or_angang(self, now):
        state = _start(_lobby(now), now)
        with pytest.raises(IllegalTransition):
            machine.declare_gang(state, expected_seq=state.seq, actor=A, target="1", now=now)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_tai": 21, "tai_table": {t: TaiPayout(hu=1, zimo=1) for t in range(1, 22)}},
            {"yao_chips": 100_001},
            {"base_chips": -1},
        ],
    )
    def test_rules_out_of_range_are_rejected(self, kwargs):
        with pytest.raises(ValidationError):
            MahjongRules(**kwargs)

    def test_negative_tai_payout_is_rejected(self):
        with pytest.raises(ValidationError):
            TaiPayout(hu=-5, zimo=1)

    def test_event_from_another_room_is_refused(self, now):
        state = _lobby(now)
        other = RoomState.new(room_id=letter_id("other"), host_id=A, host_display_name="A", now=now)
        events = machine.join_player(
            other, expected_seq=other.seq, player_id=E, display_name="x", now=now
        )
        with pytest.raises(ValueError):
            machine.fold(state, events)


def test_money_from_a_hand_ended_mid_way_counts_in_the_profit_breakdown(now):
    state = _start(_lobby(now), now)
    state = machine.fold(
        state,
        machine.declare_yao(
            state, expected_seq=state.seq, actor=B, target_seat=0, an=False, now=now
        ),
    )
    state = machine.fold(state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now))
    stats = mahjong_hand_stats([state])
    for pid, s in stats.items():
        assert sum(s.profit_by_kind.values()) == state.balances[pid]


def test_a_game_started_under_looser_rules_still_replays(now):
    state = _lobby(now)
    events = machine.start_game(
        state, expected_seq=state.seq, actor=A, rules=MahjongRules(), now=now
    )
    rules = MahjongRules().model_dump(mode="json")
    rules["tai_table"]["1"] = {"hu": 5_000_000, "zimo": 1}
    old_style = events[0].model_copy(update={"payload": {"rules": rules}})
    replayed = machine.fold(state, [old_style])
    assert replayed.rules is not None and replayed.rules.tai_table[1].hu == 5_000_000
