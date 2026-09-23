"""The bell: everything waiting on YOU, and nothing that isn't."""

from __future__ import annotations

RULES = {"card_value_cents": 100, "base_cards": 1}


async def _settled_game(host, guest):
    """Host wins, so `guest` ends up owing them."""
    r = await host.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await guest.get(f"/rooms/by-code/{invite}")
    r = await guest.post(f"/rooms/{room_id}/join")
    st = r.json()
    r = await host.post(f"/rooms/{room_id}/start", json={"expected_seq": st["seq"], "rules": RULES})
    st = r.json()
    r = await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    r = await guest.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 4})
    st = r.json()
    await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})


async def test_nothing_pending_is_an_empty_bell(make_device):
    alice = await make_device("Alice")
    r = await alice.get("/notifications")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "total": 0}


async def test_a_debt_notifies_only_the_person_who_has_to_act(make_device):
    alice = await make_device("Alice")  # wins, is owed
    bob = await make_device("Bob")  # loses, owes
    await _settled_game(alice, bob)

    # Bob has to pay, so it's his action, not Alice's.
    bob_bell = (await bob.get("/notifications")).json()
    assert bob_bell["total"] == 1
    assert bob_bell["items"][0]["kind"] == "debt_to_pay"
    assert bob_bell["items"][0]["counterparty"] == "Alice"
    assert bob_bell["items"][0]["amount_cents"] > 0
    assert (await alice.get("/notifications")).json()["total"] == 0

    # Once Bob says he's paid, the ball is in Alice's court and out of his.
    settlement_id = (await bob.get("/debts/me")).json()["owing"][0]["settlement_id"]
    await bob.post(f"/debts/{settlement_id}/mark-paid")
    assert (await bob.get("/notifications")).json()["total"] == 0
    alice_bell = (await alice.get("/notifications")).json()
    assert alice_bell["total"] == 1
    assert alice_bell["items"][0]["kind"] == "debt_to_approve"
    assert alice_bell["items"][0]["counterparty"] == "Bob"

    # Approving clears it for everyone.
    await alice.post(f"/debts/{settlement_id}/approve")
    assert (await alice.get("/notifications")).json()["total"] == 0
    assert (await bob.get("/notifications")).json()["total"] == 0


async def test_friend_requests_notify_the_recipient_only(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await alice.get("/users/me")
    await bob.get("/users/me")

    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    assert (await alice.get("/notifications")).json()["total"] == 0  # waiting on Bob
    bell = (await bob.get("/notifications")).json()
    assert bell["total"] == 1
    assert bell["items"][0]["kind"] == "friend_request"
    assert bell["items"][0]["counterparty"] == "Alice"
    assert bell["items"][0]["amount_cents"] is None

    edge_id = bell["items"][0]["ref_id"]
    await bob.post(f"/friends/requests/{edge_id}/accept")
    assert (await bob.get("/notifications")).json()["total"] == 0


async def test_everything_pending_appears_together(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")
    await _settled_game(alice, bob)  # Bob owes Alice
    await cara.get("/users/me")
    await bob.get("/users/me")
    await cara.post("/friends/requests", json={"user_id": bob.user_id})

    bell = (await bob.get("/notifications")).json()
    assert bell["total"] == 2
    assert {i["kind"] for i in bell["items"]} == {"debt_to_pay", "friend_request"}
