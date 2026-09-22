"""Recovering from the mistakes playtesting turned up: a mistyped card
count, an accidental win claim, and a stray special-hand tap.
"""

from __future__ import annotations

RULES = {"card_value_cents": 100, "base_cards": 1, "special_hand_cards": 5}


async def _started_room(make_device, n=3):
    devices = [await make_device(f"P{i}") for i in range(n)]
    host, guests = devices[0], devices[1:]
    r = await host.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for g in guests:
        await g.get(f"/rooms/by-code/{invite}")
        r = await g.post(f"/rooms/{room_id}/join")
    st = r.json()
    r = await host.post(f"/rooms/{room_id}/start", json={"expected_seq": st["seq"], "rules": RULES})
    return room_id, devices, r.json()


async def test_zero_cards_is_rejected_not_a_crash(make_device):
    room_id, (host, p1, p2), st = await _started_room(make_device)
    r = await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()

    r = await p1.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 0})
    assert r.status_code == 400, r.text  # a 500 here is the bug this covers
    assert "1 card" in r.json()["detail"]

    # Negative is still rejected, and the round is untouched — a valid
    # resubmission goes straight through.
    assert (
        await p1.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": -1})
    ).status_code == 400
    r = await p1.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 3})
    assert r.status_code == 200, r.text
    assert r.json()["rounds"][-1]["cards_submitted"][p1.user_id] == 3
    del p2


async def test_host_can_cancel_an_accidental_win_claim(make_device):
    room_id, (host, p1, p2), st = await _started_room(make_device)
    r = await p1.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    assert st["rounds"][-1]["phase"] == "collecting"

    # Only the host may void.
    assert (
        await p2.post(f"/rooms/{room_id}/void", json={"expected_seq": st["seq"]})
    ).status_code == 403

    r = await host.post(f"/rooms/{room_id}/void", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    round_ = r.json()["rounds"][-1]
    assert round_["phase"] == "playing"
    assert round_["winner"] is None
    assert all(v == 0 for v in r.json()["balances"].values())

    # And the round can then be played properly.
    r = await p2.post(f"/rooms/{room_id}/win", json={"expected_seq": r.json()["seq"]})
    assert r.status_code == 200, r.text


async def test_accidental_special_hand_can_be_taken_back(make_device):
    room_id, (host, p1, p2), st = await _started_room(make_device)

    r = await p1.post(f"/rooms/{room_id}/special", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()
    charged = st["balances"][p1.user_id]
    assert charged > 0 and st["balances"][host.user_id] < 0
    assert st["rounds"][-1]["special_counts"][p1.user_id] == 1

    # Someone else's claim isn't yours to undo.
    assert (
        await p2.post(f"/rooms/{room_id}/void-special", json={"expected_seq": st["seq"]})
    ).status_code == 400

    r = await p1.post(f"/rooms/{room_id}/void-special", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()
    assert all(v == 0 for v in st["balances"].values()), st["balances"]
    assert st["rounds"][-1]["special_counts"].get(p1.user_id, 0) == 0
    assert st["rounds"][-1]["transfers"] == []

    # Nothing left to undo.
    assert (
        await p1.post(f"/rooms/{room_id}/void-special", json={"expected_seq": st["seq"]})
    ).status_code == 400


async def test_undoing_one_special_leaves_the_others(make_device):
    room_id, (host, p1, p2), st = await _started_room(make_device)
    for _ in range(2):
        r = await p1.post(f"/rooms/{room_id}/special", json={"expected_seq": st["seq"]})
        st = r.json()
    r = await p2.post(f"/rooms/{room_id}/special", json={"expected_seq": st["seq"]})
    st = r.json()
    two_claims_plus_one = st["balances"][p1.user_id]

    r = await p1.post(f"/rooms/{room_id}/void-special", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()
    # P1 keeps one claim; P2's is untouched.
    assert st["rounds"][-1]["special_counts"][p1.user_id] == 1
    assert st["rounds"][-1]["special_counts"][p2.user_id] == 1
    assert st["balances"][p1.user_id] < two_claims_plus_one
    assert st["balances"][p2.user_id] > 0
    # Money still adds up to zero across the table.
    assert sum(st["balances"].values()) == 0
    del host


async def test_the_claimer_can_cancel_their_own_win(make_device):
    """The person who misclicked shouldn't have to find the host."""
    room_id, (host, p1, p2), st = await _started_room(make_device)
    r = await p1.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()

    # Not a free-for-all: an uninvolved player still can't undo it.
    assert (
        await p2.post(f"/rooms/{room_id}/void", json={"expected_seq": st["seq"]})
    ).status_code == 403

    r = await p1.post(f"/rooms/{room_id}/void", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    assert r.json()["rounds"][-1]["phase"] == "playing"
    del host


async def test_only_the_host_can_end_the_game(make_device):
    room_id, (host, p1, p2), st = await _started_room(make_device)
    assert (
        await p1.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    ).status_code == 403
    r = await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    del p2
