"""Integration tests for GET /history/me: ordering and settlement-status
counts as a room's debts transition through their lifecycle.
"""

from __future__ import annotations


async def _play_taidi_room(alice, bob):
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/start",
        json={"expected_seq": state["seq"], "rules": {"card_value_cents": 100, "base_cards": 1}},
    )
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    state = r.json()
    r = await bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 1})
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    return room_id


async def test_empty_history(make_device):
    alice = await make_device("Alice")
    r = await alice.get("/history/me")
    assert r.status_code == 200, r.text
    assert r.json()["games"] == []


async def test_history_shows_pending_then_settled(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id = await _play_taidi_room(alice, bob)

    r = await alice.get("/history/me")
    game = r.json()["games"][0]
    assert game["room_id"] == room_id
    assert game["game_type"] == "taidi"
    assert game["net_cents"] == 200
    assert game["settlements_total"] == 1
    assert game["settlements_pending"] == 1
    assert game["settlements_needs_my_approval"] == 0
    assert game["all_settled"] is False

    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]
    await bob.post(f"/debts/{settlement_id}/mark-paid")

    game = (await alice.get("/history/me")).json()["games"][0]
    assert game["settlements_pending"] == 1  # marked_paid still counts as pending
    assert game["settlements_needs_my_approval"] == 1  # Alice is the winner here
    assert game["all_settled"] is False

    # Bob's own view: it's his debt, not something he needs to approve.
    bob_game = (await bob.get("/history/me")).json()["games"][0]
    assert bob_game["settlements_needs_my_approval"] == 0

    await alice.post(f"/debts/{settlement_id}/approve")
    game = (await alice.get("/history/me")).json()["games"][0]
    assert game["settlements_pending"] == 0
    assert game["all_settled"] is True


async def test_history_is_most_recent_first(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    first_room = await _play_taidi_room(alice, bob)
    second_room = await _play_taidi_room(alice, bob)

    games = (await alice.get("/history/me")).json()["games"]
    assert [g["room_id"] for g in games] == [second_room, first_room]
