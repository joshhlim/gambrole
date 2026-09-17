"""Per-session fact counters — the primitives the stats page filters and
sums. Focused on the metrics that didn't exist before: trapping (Taidi),
and shooting / concealed declarations (Mahjong).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from mahjong_core import machine as mj
from mahjong_core.models import MahjongRules
from mahjong_core.models import RoomState as MjRoom
from mahjong_core.stats import mahjong_session_facts
from taidi_core import machine as td
from taidi_core.models import GameRules
from taidi_core.models import RoomState as TdRoom
from taidi_core.stats import taidi_session_facts

NOW = datetime(2026, 1, 1, tzinfo=UTC)
# double at 3+, triple at 5+ — small thresholds keep the fixtures readable.
RULES = GameRules(card_value_cents=100, base_cards=1, double_threshold=3, triple_threshold=5)


def _taidi_room(players):
    """A started 3-player Taidi room. players = [(id, name), ...]."""
    (host_id, host_name), *rest = players
    state = TdRoom.new(room_id=uuid4(), host_id=host_id, host_display_name=host_name, now=NOW)
    for pid, name in rest:
        state = td.fold(
            state,
            td.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=name, now=NOW
            ),
        )
    return td.fold(
        state,
        td.start_game(state, expected_seq=state.seq, actor=host_id, rules=RULES, now=NOW),
    )


def _play_round(state, winner, cards_by_player):
    state = td.fold(state, td.claim_win(state, expected_seq=state.seq, actor=winner, now=NOW))
    for pid, cards in cards_by_player.items():
        state = td.fold(
            state,
            td.submit_cards(state, expected_seq=state.seq, actor=pid, cards=cards, now=NOW),
        )
    return state


def test_trapping_counts_only_wins_that_caught_someone():
    a, b, c = uuid4(), uuid4(), uuid4()
    state = _taidi_room([(a, "A"), (b, "B"), (c, "C")])

    # Round 1: A wins, nobody over the double threshold -> not a trap.
    state = _play_round(state, a, {b: 1, c: 2})
    # Round 2: A wins and B is left on 5 cards (triple) -> a trap.
    state = _play_round(state, a, {b: 5, c: 1})
    # Round 3: B wins, A left on 4 (double) -> a trap for B, not for A.
    state = _play_round(state, b, {a: 4, c: 1})

    fa = taidi_session_facts(state, a)
    assert fa.rounds_played == 3
    assert fa.rounds_won == 2
    assert fa.trapping_wins == 1
    # A only paid in round 3, on 4 cards -> exactly one doubled round.
    assert fa.payer_rounds == 1
    assert fa.double_rounds == 1
    assert fa.triple_rounds == 0

    fb = taidi_session_facts(state, b)
    assert fb.rounds_won == 1
    assert fb.trapping_wins == 1  # caught A on a double
    assert fb.triple_rounds == 1  # B's own 5-card round


def _mahjong_room():
    ids = [uuid4() for _ in range(4)]
    state = MjRoom.new(room_id=uuid4(), host_id=ids[0], host_display_name="P0", now=NOW)
    for i, pid in enumerate(ids[1:], start=1):
        state = mj.fold(
            state,
            mj.join_player(
                state, expected_seq=state.seq, player_id=pid, display_name=f"P{i}", now=NOW
            ),
        )
    state = mj.fold(
        state,
        mj.start_game(state, expected_seq=state.seq, actor=ids[0], rules=MahjongRules(), now=NOW),
    )
    return state, ids


def test_concealed_declarations_are_distinguished():
    state, ids = _mahjong_room()
    p0, p1 = ids[0], ids[1]

    state = mj.fold(
        state,
        mj.declare_yao(state, expected_seq=state.seq, actor=p0, target_seat=1, an=False, now=NOW),
    )
    state = mj.fold(
        state,
        mj.declare_yao(state, expected_seq=state.seq, actor=p0, target_seat=0, an=True, now=NOW),
    )
    state = mj.fold(
        state, mj.declare_gang(state, expected_seq=state.seq, actor=p0, target="angang", now=NOW)
    )
    state = mj.fold(
        state, mj.declare_gang(state, expected_seq=state.seq, actor=p0, target=1, now=NOW)
    )
    state = mj.fold(
        state,
        mj.declare_hu(
            state, expected_seq=state.seq, actor=p0, mode="direct", target_seat=1, tai=1, now=NOW
        ),
    )

    f = mahjong_session_facts(state, p0)
    assert (f.yao_count, f.anyao_count) == (1, 1)
    assert (f.gang_count, f.angang_count) == (1, 1)
    # The opponent declared none of them.
    f1 = mahjong_session_facts(state, p1)
    assert (f1.yao_count, f1.anyao_count, f1.gang_count, f1.angang_count) == (0, 0, 0, 0)


def test_shooting_counts_direct_losses_but_not_zimo():
    state, ids = _mahjong_room()
    p0, p1 = ids[0], ids[1]

    # P0 wins directly off P1 -> P1 shot.
    state = mj.fold(
        state,
        mj.declare_hu(
            state, expected_seq=state.seq, actor=p0, mode="direct", target_seat=1, tai=1, now=NOW
        ),
    )
    # P0 wins by zimo -> P1 pays, but didn't shoot.
    state = mj.fold(
        state,
        mj.declare_hu(
            state,
            expected_seq=state.seq,
            actor=p0,
            mode="zimo",
            target_seat=None,
            tai=1,
            now=NOW,
        ),
    )

    f1 = mahjong_session_facts(state, p1)
    assert f1.lost_hands == 2
    assert f1.shot_hands == 1

    f0 = mahjong_session_facts(state, p0)
    assert f0.hands_won == 2
    assert f0.zimo_wins == 1
    assert f0.direct_wins == 1
    assert f0.shot_hands == 0
    assert f0.tai_wins == 2 and f0.tai_total == 2
