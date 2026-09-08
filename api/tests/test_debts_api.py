"""Integration tests for the settlements read-model: settlement creation on
game_ended, GET /debts/me, and the mark-paid/approve/reject lifecycle.
"""

from __future__ import annotations


async def _play_taidi_room(alice, bob):
    """Alice wins, Bob pays 1 card at card_value_cents=100, base_cards=1 ->
    Bob owes Alice 200 cents. Mirrors test_stats_api.py's exact scenario."""
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()

    r = await alice.post(
        f"/rooms/{room_id}/start",
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
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    state = r.json()
    r = await bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 1})
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    return room_id


async def test_ending_a_room_creates_a_pending_settlement(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id = await _play_taidi_room(alice, bob)

    a = (await alice.get("/debts/me")).json()
    assert a["owing"] == []
    assert len(a["owed"]) == 1
    debt = a["owed"][0]
    assert debt["room_id"] == room_id
    assert debt["game_type"] == "taidi"
    assert debt["amount_cents"] == 200
    assert debt["status"] == "pending"
    assert debt["counterparty_id"] == bob.user_id
    assert debt["counterparty_display_name"] == "Bob"

    b = (await bob.get("/debts/me")).json()
    assert b["owed"] == []
    assert len(b["owing"]) == 1
    assert b["owing"][0]["amount_cents"] == 200
    assert b["owing"][0]["counterparty_display_name"] == "Alice"


async def test_disbanded_room_creates_no_settlement(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    r = await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": 0})
    assert r.status_code == 200, r.text

    a = (await alice.get("/debts/me")).json()
    assert a["owing"] == [] and a["owed"] == []


async def test_mahjong_settlement_converts_chips_to_cents(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")
    dan = await make_device("Dan")
    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    for d in (bob, cara, dan):
        await d.get(f"/rooms/by-code/{invite}")
        await d.post(f"/rooms/{room_id}/mahjong/join")
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    state = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={"expected_seq": state["seq"], "mode": "direct", "target_seat": 1, "tai": 1},
    )
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/mahjong/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    # Bob (seat 1) pays Alice 4 chips at the default table -> 4 * 50 = 200 cents.
    a = (await alice.get("/debts/me")).json()
    assert len(a["owed"]) == 1
    assert a["owed"][0]["amount_cents"] == 200
    assert a["owed"][0]["game_type"] == "mahjong"


async def test_mark_paid_then_approve_lifecycle(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play_taidi_room(alice, bob)
    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]

    r = await bob.post(f"/debts/{settlement_id}/mark-paid")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "marked_paid"

    # Reflected on both sides.
    assert (await bob.get("/debts/me")).json()["owing"][0]["status"] == "marked_paid"
    assert (await alice.get("/debts/me")).json()["owed"][0]["status"] == "marked_paid"

    r = await alice.post(f"/debts/{settlement_id}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert (await bob.get("/debts/me")).json()["owing"][0]["status"] == "approved"


async def test_reject_reverts_to_pending(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play_taidi_room(alice, bob)
    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]

    await bob.post(f"/debts/{settlement_id}/mark-paid")
    r = await alice.post(f"/debts/{settlement_id}/reject")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    assert (await bob.get("/debts/me")).json()["owing"][0]["status"] == "pending"

    # Bob can mark it paid again after a reject.
    r = await bob.post(f"/debts/{settlement_id}/mark-paid")
    assert r.status_code == 200, r.text


async def test_wrong_actor_gets_403(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play_taidi_room(alice, bob)
    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]

    # Alice (the winner) can't mark her own receivable as paid.
    r = await alice.post(f"/debts/{settlement_id}/mark-paid")
    assert r.status_code == 403

    await bob.post(f"/debts/{settlement_id}/mark-paid")

    # Bob (the loser) can't approve or reject his own debt.
    r = await bob.post(f"/debts/{settlement_id}/approve")
    assert r.status_code == 403
    r = await bob.post(f"/debts/{settlement_id}/reject")
    assert r.status_code == 403


async def test_double_mark_paid_conflicts(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play_taidi_room(alice, bob)
    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]

    r = await bob.post(f"/debts/{settlement_id}/mark-paid")
    assert r.status_code == 200, r.text
    r = await bob.post(f"/debts/{settlement_id}/mark-paid")
    assert r.status_code == 409

    # Approving a still-pending debt (never marked paid) also conflicts.
    alice2 = await make_device("Alice2")
    bob2 = await make_device("Bob2")
    await _play_taidi_room(alice2, bob2)
    other_id = (await bob2.get("/debts/me")).json()["owing"][0]["settlement_id"]
    r = await alice2.post(f"/debts/{other_id}/approve")
    assert r.status_code == 409
