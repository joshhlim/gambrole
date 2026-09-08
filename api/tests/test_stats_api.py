"""Integration tests for GET /stats/me against a real Postgres database.

This endpoint's whole value is numerical precision — every test here plays
out a small room with a deliberately chosen outcome and asserts exact
numbers, not just a 200 OK.
"""

from __future__ import annotations


async def test_zero_ended_rooms_returns_well_formed_empty_response(make_device):
    alice = await make_device("Alice")

    r = await alice.get("/stats/me")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["overview"]["total_cents"] == 0
    assert body["overview"]["total_sessions"] == 0
    assert body["overview"]["current_streak"] == 0
    assert body["overview"]["favorite_game"] is None
    assert body["overview"]["last_played"] is None
    assert body["overview"]["trend"] == []
    assert body["taidi"] is None
    assert body["mahjong"] is None


async def test_stats_combine_taidi_and_mahjong_with_exact_numbers(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    # --- Taidi: 2 players, Alice wins, Bob pays 1 card (below the double
    # band) at card_value_cents=100, base_cards=1 -> Bob pays Alice
    # 1*1*100 (cards) + 1*100 (base) = 200.
    r = await alice.post("/rooms")
    taidi_room_id = r.json()["room_id"]
    taidi_invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{taidi_invite}")
    r = await bob.post(f"/rooms/{taidi_room_id}/join")
    state = r.json()

    r = await alice.post(
        f"/rooms/{taidi_room_id}/start",
        json={
            "expected_seq": state["seq"],
            "rules": {
                "card_value_cents": 100,
                "base_cards": 1,
                "double_threshold": 3,
                "triple_threshold": 5,
            },
        },
    )
    state = r.json()
    r = await alice.post(f"/rooms/{taidi_room_id}/win", json={"expected_seq": state["seq"]})
    state = r.json()
    r = await bob.post(
        f"/rooms/{taidi_room_id}/cards", json={"expected_seq": state["seq"], "cards": 1}
    )
    assert r.status_code == 200, r.text
    state = r.json()
    r = await alice.post(f"/rooms/{taidi_room_id}/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    # --- Mahjong: 4 players, Alice HUs directly off Bob (seat 1) at 1 tai
    # against the default "3/6 半" table (hu(1)=4) -> Bob pays Alice 4 chips.
    cara = await make_device("Cara")
    dan = await make_device("Dan")
    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    mj_room_id = r.json()["room_id"]
    mj_invite = r.json()["invite_code"]
    for d in (bob, cara, dan):
        await d.get(f"/rooms/by-code/{mj_invite}")
        r = await d.post(f"/rooms/{mj_room_id}/mahjong/join")
        assert r.status_code == 200, r.text
    state = (await alice.get(f"/rooms/{mj_room_id}/state")).json()
    r = await alice.post(
        f"/rooms/{mj_room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    state = r.json()
    r = await alice.post(
        f"/rooms/{mj_room_id}/mahjong/hu",
        json={"expected_seq": state["seq"], "mode": "direct", "target_seat": 1, "tai": 1},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    r = await alice.post(f"/rooms/{mj_room_id}/mahjong/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    # --- Alice's stats: +200 cents (taidi) + 4 chips * 50 = 200 cents (mahjong).
    r = await alice.get("/stats/me")
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["overview"]["taidi_cents"] == 200
    assert a["overview"]["mahjong_cents"] == 200
    assert a["overview"]["mahjong_chips"] == 4
    assert a["overview"]["total_cents"] == 400
    assert a["overview"]["taidi_sessions"] == 1
    assert a["overview"]["mahjong_sessions"] == 1
    assert a["overview"]["total_sessions"] == 2
    assert a["overview"]["favorite_game"] == "tied"
    assert a["overview"]["current_streak"] == 2  # both sessions profited
    assert len(a["overview"]["trend"]) == 2

    assert a["taidi"]["rounds_played"] == 1
    assert a["taidi"]["round_wins"] == 1
    assert a["taidi"]["round_win_rate"] == 1.0
    assert a["taidi"]["profit_rounds"] == 1
    assert a["taidi"]["profit_rate"] == 1.0
    assert a["taidi"]["payer_rounds"] == 0
    assert a["taidi"]["best_round_cents"] == 200

    assert a["mahjong"]["hands_played"] == 1
    assert a["mahjong"]["hu_count"] == 1
    assert a["mahjong"]["hu_rate"] == 1.0
    assert a["mahjong"]["win_mode_counts"] == {"direct": 1}
    assert a["mahjong"]["profit_by_kind"] == {"hu": 4}
    assert a["mahjong"]["best_hand_chips"] == 4

    # --- Bob's stats: mirror image, both sessions a loss.
    r = await bob.get("/stats/me")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["overview"]["taidi_cents"] == -200
    assert b["overview"]["mahjong_cents"] == -200
    assert b["overview"]["mahjong_chips"] == -4
    assert b["overview"]["total_cents"] == -400
    assert b["overview"]["current_streak"] == -2

    assert b["taidi"]["rounds_played"] == 1
    assert b["taidi"]["round_wins"] == 0
    assert b["taidi"]["payer_rounds"] == 1
    assert b["taidi"]["double_rounds"] == 0  # 1 card, below the double band
    assert b["taidi"]["worst_round_cents"] == -200

    assert b["mahjong"]["hands_played"] == 1
    assert b["mahjong"]["hu_count"] == 0
    assert b["mahjong"]["hu_rate"] == 0.0
    assert b["mahjong"]["dealer_hands"] == 0  # Bob is seat 1, dealer was seat 0
    assert b["mahjong"]["profit_by_kind"] == {"hu": -4}

    # --- Cara/Dan only played the mahjong room, not the taidi one.
    r = await cara.get("/stats/me")
    c = r.json()
    assert c["overview"]["taidi_sessions"] == 0
    assert c["overview"]["mahjong_sessions"] == 1
    assert c["overview"]["favorite_game"] == "mahjong"
    assert c["taidi"] is None
    assert c["mahjong"]["hands_played"] == 1
    assert c["mahjong"]["hu_count"] == 0
