"""The Mahjong room/hand state machine: legal transitions, illegal ones, and settlement math."""

from __future__ import annotations

import pytest
from mahjong_core import machine
from mahjong_core.models import MahjongRules, RoomState, TaiPayout
from taidi_core.errors import IllegalTransition, NotAuthorized, SeqConflict
from taidi_core.models import RoomStatus

from .conftest import letter_id

A, B, C, D = letter_id("A"), letter_id("B"), letter_id("C"), letter_id("D")


def _tai_rules(**overrides) -> MahjongRules:
    """5 clean, distinct tai levels (hu=100*tai, zimo=50*tai) — not the real
    3/6 半 numbers, just easy-to-check round values for testing the lookup
    mechanism itself. See test_mahjong_rules_fixtures.py for the actual
    preset's numbers."""
    table = {t: TaiPayout(hu=100 * t, zimo=50 * t) for t in range(1, 6)}
    return MahjongRules(max_tai=5, tai_table=table, **overrides)


def _room(now) -> RoomState:
    """A lobby with exactly 4 players, seated in join order A=0, B=1, C=2, D=3."""
    state = RoomState.new(room_id=letter_id("room"), host_id=A, host_display_name="A", now=now)
    for pid, name in [(B, "B"), (C, "C"), (D, "D")]:
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=now
            ),
        )
    return state


def _started_room(now, rules: MahjongRules | None = None) -> RoomState:
    state = _room(now)
    return machine.fold(
        state,
        machine.start_game(
            state, expected_seq=state.seq, actor=A, rules=rules or MahjongRules(), now=now
        ),
    )


class TestLobby:
    def test_join_then_start(self, now):
        state = _room(now)
        assert len(state.members) == 4
        state = machine.fold(
            state,
            machine.start_game(
                state, expected_seq=state.seq, actor=A, rules=MahjongRules(), now=now
            ),
        )
        assert state.status == RoomStatus.IN_PROGRESS
        assert len(state.hands) == 1
        assert state.hands[0].hand_no == 1
        assert state.hands[0].wind == 1
        assert state.hands[0].dealer_seat == 0

    def test_fifth_player_rejected(self, now):
        state = _room(now)
        with pytest.raises(IllegalTransition):
            machine.join_player(
                state,
                expected_seq=state.seq,
                player_id=letter_id("E"),
                display_name="E",
                now=now,
            )

    def test_cannot_start_with_fewer_than_four(self, now):
        state = RoomState.new(room_id=letter_id("room"), host_id=A, host_display_name="A", now=now)
        state = machine.fold(
            state,
            machine.join_player(
                state, expected_seq=state.seq, player_id=B, display_name="B", now=now
            ),
        )
        with pytest.raises(IllegalTransition):
            machine.start_game(
                state, expected_seq=state.seq, actor=A, rules=MahjongRules(), now=now
            )

    def test_only_host_can_start(self, now):
        state = _room(now)
        with pytest.raises(NotAuthorized):
            machine.start_game(
                state, expected_seq=state.seq, actor=B, rules=MahjongRules(), now=now
            )

    def test_stale_seq_rejected(self, now):
        state = _room(now)
        with pytest.raises(SeqConflict):
            machine.start_game(
                state, expected_seq=state.seq + 5, actor=A, rules=MahjongRules(), now=now
            )

    def test_assign_seats_reorders(self, now):
        state = _room(now)
        state = machine.fold(
            state,
            machine.assign_seats(
                state,
                expected_seq=state.seq,
                actor=A,
                seat_map={A: 3, B: 2, C: 1, D: 0},
                now=now,
            ),
        )
        assert state.member_ids_by_seat == [D, C, B, A]

    def test_assign_seats_rejects_incomplete_mapping(self, now):
        state = _room(now)
        with pytest.raises(IllegalTransition):
            machine.assign_seats(
                state, expected_seq=state.seq, actor=A, seat_map={A: 0, B: 1}, now=now
            )

    def test_assign_seats_rejects_duplicate_seat(self, now):
        state = _room(now)
        with pytest.raises(IllegalTransition):
            machine.assign_seats(
                state,
                expected_seq=state.seq,
                actor=A,
                seat_map={A: 0, B: 0, C: 1, D: 2},
                now=now,
            )

    def test_only_host_can_assign_seats(self, now):
        state = _room(now)
        with pytest.raises(NotAuthorized):
            machine.assign_seats(
                state, expected_seq=state.seq, actor=B, seat_map={A: 1, B: 0, C: 2, D: 3}, now=now
            )


class TestYao:
    def test_self_select_charges_each_other_player(self, now):
        state = _started_room(now, MahjongRules(yao_chips=2))
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=0, an=False, now=now
            ),
        )
        assert state.balances[A] == 6
        assert state.balances[B] == state.balances[C] == state.balances[D] == -2

    def test_self_select_an_doubles(self, now):
        state = _started_room(now, MahjongRules(yao_chips=2))
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=0, an=True, now=now
            ),
        )
        assert state.balances[A] == 12
        assert state.balances[B] == -4

    def test_other_select_charges_only_target(self, now):
        state = _started_room(now, MahjongRules(yao_chips=2))
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=1, an=False, now=now
            ),
        )
        assert state.balances[A] == 2
        assert state.balances[B] == -2
        assert state.balances[C] == 0
        assert state.balances[D] == 0

    def test_yao_does_not_close_the_hand(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=1, an=False, now=now
            ),
        )
        assert len(state.hands) == 1
        assert not state.hands[0].closed


class TestGang:
    def test_self_select_charges_each_other_player_once(self, now):
        state = _started_room(now, MahjongRules(gang_chips=2))
        state = machine.fold(
            state, machine.declare_gang(state, expected_seq=state.seq, actor=A, target=0, now=now)
        )
        assert state.balances[A] == 6
        assert state.balances[B] == state.balances[C] == state.balances[D] == -2
        assert state.hands[0].had_gang

    def test_other_select_charges_target_triple(self, now):
        state = _started_room(now, MahjongRules(gang_chips=2))
        state = machine.fold(
            state, machine.declare_gang(state, expected_seq=state.seq, actor=A, target=1, now=now)
        )
        assert state.balances[A] == 6
        assert state.balances[B] == -6
        assert state.balances[C] == 0

    def test_angang_charges_each_other_player_double(self, now):
        state = _started_room(now, MahjongRules(gang_chips=2))
        state = machine.fold(
            state,
            machine.declare_gang(state, expected_seq=state.seq, actor=A, target="angang", now=now),
        )
        assert state.balances[A] == 12
        assert state.balances[B] == state.balances[C] == state.balances[D] == -4

    def test_multiple_gangs_in_one_hand(self, now):
        state = _started_room(now, MahjongRules(gang_chips=2))
        state = machine.fold(
            state, machine.declare_gang(state, expected_seq=state.seq, actor=A, target=1, now=now)
        )
        state = machine.fold(
            state,
            machine.declare_gang(state, expected_seq=state.seq, actor=B, target="angang", now=now),
        )
        assert len(state.hands) == 1
        assert not state.hands[0].closed
        assert state.hands[0].had_gang


class TestHu:
    def test_direct_win_charges_only_target(self, now):
        state = _started_room(now, _tai_rules())
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=3, now=now
            ),
        )
        assert state.balances[A] == 300  # hu(3) = 100*3
        assert state.balances[B] == -300
        assert state.balances[C] == 0

    def test_zimo_charges_each_other_player(self, now):
        state = _started_room(now, _tai_rules())
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="zimo",
                target_seat=None,
                tai=2,
                now=now,
            ),
        )
        assert state.balances[A] == 300  # zimo(2)=100 each * 3 payers
        assert state.balances[B] == state.balances[C] == state.balances[D] == -100

    def test_bao_charges_target_the_full_zimo_amount(self, now):
        state = _started_room(now, _tai_rules())
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="bao", target_seat=1, tai=2, now=now
            ),
        )
        assert state.balances[A] == 300  # zimo(2)=100 * 3, all from one payer
        assert state.balances[B] == -300
        assert state.balances[C] == 0
        assert state.balances[D] == 0

    def test_hu_closes_hand_and_records_winner(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        assert state.hands[0].closed
        assert state.hands[0].winner == A
        assert state.hands[0].mode == "direct"
        assert state.hands[0].tai == 1
        assert state.hands[0].zimo_bonus is False
        assert state.hands[0].klppdd is False

    def test_hu_records_zimo_bonus_and_klppdd_flags(self, now):
        state = _started_room(now, _tai_rules(zimo_bonus_chips=5, klppdd_chips=10))
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="zimo",
                target_seat=None,
                tai=2,
                zimo_bonus=True,
                klppdd=True,
                now=now,
            ),
        )
        assert state.hands[0].mode == "zimo"
        assert state.hands[0].tai == 2
        assert state.hands[0].zimo_bonus is True
        assert state.hands[0].klppdd is True

    def test_no_win_leaves_hu_fields_unset(self, now):
        state = _started_room(now)
        state = machine.fold(
            state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.hands[0].closed
        assert state.hands[0].winner is None
        assert state.hands[0].mode is None
        assert state.hands[0].tai is None
        assert state.hands[0].zimo_bonus is False
        assert state.hands[0].klppdd is False

    def test_tai_out_of_range_rejected(self, now):
        state = _started_room(now, MahjongRules(max_tai=5))
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=6, now=now
            )
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=0, now=now
            )

    def test_cannot_target_self_for_direct_or_bao(self, now):
        state = _started_room(now)
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=0, tai=1, now=now
            )
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="bao", target_seat=0, tai=1, now=now
            )

    def test_zimo_bonus_adds_flat_amount_from_each_other_player(self, now):
        state = _started_room(now, _tai_rules(zimo_bonus_chips=5))
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="zimo",
                target_seat=None,
                tai=2,
                zimo_bonus=True,
                now=now,
            ),
        )
        # zimo(2)=100 each + 5 bonus each, from 3 payers = 315
        assert state.balances[A] == 315
        assert state.balances[B] == state.balances[C] == state.balances[D] == -105

    def test_zimo_bonus_rejected_on_direct_or_bao(self, now):
        state = _started_room(now, _tai_rules(zimo_bonus_chips=5))
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="direct",
                target_seat=1,
                tai=1,
                zimo_bonus=True,
                now=now,
            )
        with pytest.raises(IllegalTransition):
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="bao",
                target_seat=1,
                tai=1,
                zimo_bonus=True,
                now=now,
            )

    def test_klppdd_splits_three_ways_on_zimo(self, now):
        state = _started_room(now, _tai_rules(klppdd_chips=10))
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="zimo",
                target_seat=None,
                tai=1,
                klppdd=True,
                now=now,
            ),
        )
        # zimo(1)=50 each + 10 klppdd each, from 3 payers = 180
        assert state.balances[A] == 180
        assert state.balances[B] == state.balances[C] == state.balances[D] == -60

    def test_klppdd_single_payer_covers_everyone_on_direct_win(self, now):
        state = _started_room(now, _tai_rules(klppdd_chips=10))
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="direct",
                target_seat=1,
                tai=1,
                klppdd=True,
                now=now,
            ),
        )
        # hu(1)=100 + 3*10 klppdd, all from B
        assert state.balances[A] == 130
        assert state.balances[B] == -130
        assert state.balances[C] == 0
        assert state.balances[D] == 0

    def test_klppdd_stacks_with_bao(self, now):
        state = _started_room(now, _tai_rules(klppdd_chips=10))
        state = machine.fold(
            state,
            machine.declare_hu(
                state,
                expected_seq=state.seq,
                actor=A,
                mode="bao",
                target_seat=1,
                tai=1,
                klppdd=True,
                now=now,
            ),
        )
        # bao(1)=zimo(1)*3=150 + 3*10 klppdd, all from B
        assert state.balances[A] == 180
        assert state.balances[B] == -180
        assert state.balances[C] == 0
        assert state.balances[D] == 0


class TestDealerWindRotation:
    """Non-final-hand rule: on a WIN, the dealer stays if the dealer
    themselves won and rotates otherwise — gang presence is irrelevant to
    a win. On a NO WIN, the dealer stays unless a gang happened this hand,
    in which case it rotates anyway."""

    def test_dealer_win_repeats_dealer(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        assert len(state.hands) == 2
        assert state.hands[1].wind == 1
        assert state.hands[1].dealer_seat == 0
        assert not state.pending_wind_decision

    def test_dealer_win_repeats_dealer_even_with_a_gang(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_gang(state, expected_seq=state.seq, actor=B, target="angang", now=now),
        )
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=A, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        assert state.hands[1].dealer_seat == 0
        assert state.hands[1].wind == 1

    def test_non_dealer_win_rotates_dealer_even_without_a_gang(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        assert state.hands[1].dealer_seat == 1
        assert state.hands[1].wind == 1

    def test_no_gang_repeats_dealer_on_no_win(self, now):
        state = _started_room(now)
        state = machine.fold(
            state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert len(state.hands) == 2
        assert state.hands[1].wind == 1
        assert state.hands[1].dealer_seat == 0

    def test_gang_on_no_win_still_rotates_dealer(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_gang(state, expected_seq=state.seq, actor=B, target="angang", now=now),
        )
        state = machine.fold(
            state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.hands[1].dealer_seat == 1

    def test_dealer_wrap_advances_wind(self, now):
        """Each hand won by whoever's next in seat order rotates the dealer
        one seat; wrapping seat 3->0 advances the wind — pure win-based
        rotation, no gangs involved."""
        state = _started_room(now)
        for winner in (B, C, D, A):
            state = machine.fold(
                state,
                machine.declare_hu(
                    state,
                    expected_seq=state.seq,
                    actor=winner,
                    mode="direct",
                    target_seat=(state.members[winner].seat + 1) % 4,
                    tai=1,
                    now=now,
                ),
            )
        assert state.hands[-1].dealer_seat == 0
        assert state.hands[-1].wind == 2


class TestFinalHandRule:
    """Wind 4, dealer seat 3 (北): a win closes the cycle; a no-win (with or
    without a gang) just repeats the same hand."""

    def _drive_to_final_hand(self, now):
        """Gangs every hand with no wins to walk straight to wind 4, seat 3."""
        state = _started_room(now)
        # 0->1->2->3 (wind 1), 0->1->2->3 (wind 2), 0->1->2->3 (wind 3),
        # then 0->1->2 (wind 4) = 15 gang+no-win hands to reach wind 4 seat 3.
        for _ in range(15):
            state = machine.fold(
                state,
                machine.declare_gang(
                    state, expected_seq=state.seq, actor=A, target="angang", now=now
                ),
            )
            state = machine.fold(
                state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
            )
        assert state.hands[-1].wind == 4
        assert state.hands[-1].dealer_seat == 3
        return state

    def test_no_win_on_final_hand_repeats_regardless_of_gang(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_gang(state, expected_seq=state.seq, actor=A, target="angang", now=now),
        )
        state = machine.fold(
            state, machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert not state.pending_wind_decision
        assert state.hands[-1].wind == 4
        assert state.hands[-1].dealer_seat == 3

    def test_win_on_final_hand_sets_pending_wind_decision(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        assert state.pending_wind_decision
        # No new hand opened yet — still on the closed final hand.
        assert state.hands[-1].closed
        assert len(state.hands) == 16

    def test_actions_blocked_while_wind_decision_pending(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        with pytest.raises(IllegalTransition):
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=1, an=False, now=now
            )
        with pytest.raises(IllegalTransition):
            machine.declare_no_win(state, expected_seq=state.seq, actor=A, now=now)

    def test_continue_wind_opens_wind_5_at_seat_0(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        state = machine.fold(
            state, machine.continue_wind(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert not state.pending_wind_decision
        assert state.hands[-1].wind == 5
        assert state.hands[-1].dealer_seat == 0
        assert not state.hands[-1].closed

    def test_only_host_can_continue_wind(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        with pytest.raises(NotAuthorized):
            machine.continue_wind(state, expected_seq=state.seq, actor=B, now=now)

    def test_continue_wind_rejected_when_nothing_pending(self, now):
        state = _started_room(now)
        with pytest.raises(IllegalTransition):
            machine.continue_wind(state, expected_seq=state.seq, actor=A, now=now)

    def test_host_can_end_instead_of_continuing(self, now):
        state = self._drive_to_final_hand(now)
        state = machine.fold(
            state,
            machine.declare_hu(
                state, expected_seq=state.seq, actor=D, mode="direct", target_seat=1, tai=1, now=now
            ),
        )
        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.status == RoomStatus.ENDED


class TestEndGame:
    def test_only_host_can_end(self, now):
        state = _started_room(now)
        with pytest.raises(NotAuthorized):
            machine.end_game(state, expected_seq=state.seq, actor=B, now=now)

    def test_host_can_end_mid_hand(self, now):
        state = _started_room(now)
        state = machine.fold(
            state,
            machine.declare_yao(
                state, expected_seq=state.seq, actor=A, target_seat=1, an=False, now=now
            ),
        )
        state = machine.fold(
            state, machine.end_game(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.status == RoomStatus.ENDED
        assert state.ended_at == now


class TestLeaveDisband:
    def test_member_can_leave_lobby(self, now):
        state = _room(now)
        state = machine.fold(
            state, machine.leave_room(state, expected_seq=state.seq, actor=B, now=now)
        )
        assert set(state.members) == {A, C, D}

    def test_host_cannot_leave(self, now):
        state = _room(now)
        with pytest.raises(IllegalTransition):
            machine.leave_room(state, expected_seq=state.seq, actor=A, now=now)

    def test_host_can_disband_lobby(self, now):
        state = _room(now)
        state = machine.fold(
            state, machine.disband_room(state, expected_seq=state.seq, actor=A, now=now)
        )
        assert state.status == RoomStatus.DISBANDED

    def test_non_host_cannot_disband(self, now):
        state = _room(now)
        with pytest.raises(NotAuthorized):
            machine.disband_room(state, expected_seq=state.seq, actor=B, now=now)
