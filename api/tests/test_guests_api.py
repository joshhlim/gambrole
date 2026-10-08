"""Guest players: seated by the host with no account, played from the host's
phone, settled one-sided, and claimable for a real account afterwards."""

from __future__ import annotations


async def _taidi_lobby(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    assert r.status_code == 201, r.text
    return alice, r.json()


async def _add_guest(host, room, name, game="taidi"):
    path = f"/rooms/{room['room_id']}" + ("/mahjong" if game == "mahjong" else "") + "/guests"
    r = await host.post(path, json={"expected_seq": room["seq"], "display_name": name})
    assert r.status_code == 200, r.text
    state = r.json()
    guest_id = next(pid for pid, m in state["members"].items() if m["display_name"] == name)
    return state, guest_id


async def _started_with_guest(make_device):
    """Alice (host, account) and Gary (guest) at a Taidi table, started."""
    alice, room = await _taidi_lobby(make_device)
    room, gary = await _add_guest(alice, room, "Gary")
    r = await alice.post(f"/rooms/{room['room_id']}/start", json={"expected_seq": room["seq"]})
    assert r.status_code == 200, r.text
    return alice, gary, r.json()


async def _finished_game_guest_won(make_device):
    """Gary (guest) wins a round off Alice, then Alice ends the game."""
    alice, gary, st = await _started_with_guest(make_device)
    room_id = st["room_id"]
    st = (
        await alice.post(
            f"/rooms/{room_id}/win",
            json={"expected_seq": st["seq"], "round_no": 1, "as_player": gary},
        )
    ).json()
    st = (
        await alice.post(
            f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "round_no": 1, "cards": 5}
        )
    ).json()
    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    return alice, gary, r.json()


# ---------- seating ----------


async def test_host_seats_and_removes_a_guest(make_device):
    alice, room = await _taidi_lobby(make_device)
    room, gary = await _add_guest(alice, room, "Gary")
    assert room["members"][gary]["is_guest"] is True

    r = await alice.post(
        f"/rooms/{room['room_id']}/guests",
        json={"expected_seq": room["seq"], "display_name": "gary"},
    )
    assert r.status_code == 400  # same name, any case

    r = await alice.post(
        f"/rooms/{room['room_id']}/guests/{gary}/remove", json={"expected_seq": room["seq"]}
    )
    assert r.status_code == 200, r.text
    assert gary not in r.json()["members"]
    assert (await alice.get(f"/rooms/{room['room_id']}/guest-claims")).json()["guests"] == []


async def test_only_the_host_seats_guests(make_device):
    alice, room = await _taidi_lobby(make_device)
    bob = await make_device("Bob")
    await bob.post(f"/rooms/{room['room_id']}/join")
    st = (await alice.get(f"/rooms/{room['room_id']}/state")).json()
    r = await bob.post(
        f"/rooms/{room['room_id']}/guests", json={"expected_seq": st["seq"], "display_name": "Gary"}
    )
    assert r.status_code == 403


# ---------- acting for a guest ----------


async def test_host_plays_a_guests_turns(make_device):
    alice, gary, st = await _started_with_guest(make_device)
    room_id = st["room_id"]
    r = await alice.post(
        f"/rooms/{room_id}/win", json={"expected_seq": st["seq"], "round_no": 1, "as_player": gary}
    )
    assert r.status_code == 200, r.text
    assert r.json()["rounds"][0]["winner"] == gary


async def test_nobody_else_can_act_for_a_guest_or_for_another_account(make_device):
    alice, room = await _taidi_lobby(make_device)
    bob = await make_device("Bob")
    await bob.post(f"/rooms/{room['room_id']}/join")
    room = (await alice.get(f"/rooms/{room['room_id']}/state")).json()
    room, gary = await _add_guest(alice, room, "Gary")
    st = (
        await alice.post(f"/rooms/{room['room_id']}/start", json={"expected_seq": room["seq"]})
    ).json()
    body = {"expected_seq": st["seq"], "round_no": 1}
    assert (
        await bob.post(f"/rooms/{room['room_id']}/win", json={**body, "as_player": gary})
    ).status_code == 403
    assert (
        await alice.post(f"/rooms/{room['room_id']}/win", json={**body, "as_player": bob.user_id})
    ).status_code == 403


async def test_mahjong_table_with_guests(make_device):
    alice = await make_device("Alice")
    room = (await alice.post("/rooms", json={"game_type": "mahjong"})).json()
    guests = []
    for name in ("Gary", "Gina", "Gus"):
        room, gid = await _add_guest(alice, room, name, game="mahjong")
        guests.append(gid)
    r = await alice.post(
        f"/rooms/{room['room_id']}/mahjong/guests",
        json={"expected_seq": room["seq"], "display_name": "Fifth"},
    )
    assert r.status_code == 400  # four seats
    st = (
        await alice.post(
            f"/rooms/{room['room_id']}/mahjong/start", json={"expected_seq": room["seq"]}
        )
    ).json()
    r = await alice.post(
        f"/rooms/{room['room_id']}/mahjong/yao",
        json={"expected_seq": st["seq"], "hand_no": 1, "target_seat": 0, "as_player": guests[0]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["balances"][guests[0]] > 0


# ---------- debts with a guest ----------


async def test_a_debt_with_a_guest_is_settled_one_sided(make_device):
    alice, gary, _st = await _finished_game_guest_won(make_device)
    owing = (await alice.get("/debts/me")).json()["owing"]
    assert len(owing) == 1
    debt = owing[0]
    assert debt["counterparty_is_guest"] is True
    assert debt["counterparty_display_name"] == "Gary"

    stranger = await make_device("Eve")
    assert (await stranger.post(f"/debts/{debt['settlement_id']}/settle")).status_code == 403

    r = await alice.post(f"/debts/{debt['settlement_id']}/settle")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"


# ---------- claiming ----------


async def test_claim_moves_the_game_onto_a_new_account(make_device):
    alice, gary, st = await _finished_game_guest_won(make_device)
    room_id = st["room_id"]
    claims = (await alice.get(f"/rooms/{room_id}/guest-claims")).json()["guests"]
    assert [c["display_name"] for c in claims] == ["Gary"]
    token = claims[0]["claim_token"]

    preview = (await alice._client.get(f"/guests/claim/{token}")).json()
    assert preview["display_name"] == "Gary" and preview["claimed"] is False
    assert preview["net_cents"] > 0

    gareth = await make_device("Gareth")
    r = await gareth.post(f"/guests/claim/{token}")
    assert r.status_code == 200, r.text

    # Now Gareth's: the game, its stats, the debt Alice owes him, the room.
    history = (await gareth.get("/history/me")).json()["games"]
    assert [g["room_id"] for g in history] == [room_id]
    facts = (await gareth.get("/stats/facts")).json()["sessions"]
    assert facts[0]["net_cents"] == preview["net_cents"]
    assert (await gareth.get(f"/rooms/{room_id}/state")).status_code == 200
    owed = (await gareth.get("/debts/me")).json()["owed"]
    assert [d["amount_cents"] for d in owed] == [preview["net_cents"]]

    # Alice sees Gareth now, not a guest, so the normal two-step applies.
    alice_debt = (await alice.get("/debts/me")).json()["owing"][0]
    assert alice_debt["counterparty_id"] == gareth.user_id
    assert alice_debt["counterparty_is_guest"] is False
    assert (await alice.post(f"/debts/{alice_debt['settlement_id']}/mark-paid")).status_code == 200
    assert (await gareth.post(f"/debts/{alice_debt['settlement_id']}/approve")).status_code == 200

    assert (await (await make_device("Other")).post(f"/guests/claim/{token}")).status_code == 409
    del gary


async def test_cant_claim_before_the_game_ends(make_device):
    alice, _gary, st = await _started_with_guest(make_device)
    token = (await alice.get(f"/rooms/{st['room_id']}/guest-claims")).json()["guests"][0][
        "claim_token"
    ]
    r = await (await make_device("Gareth")).post(f"/guests/claim/{token}")
    assert r.status_code == 409


async def test_cant_claim_a_guest_in_a_game_you_played(make_device):
    alice, _gary, st = await _finished_game_guest_won(make_device)
    token = (await alice.get(f"/rooms/{st['room_id']}/guest-claims")).json()["guests"][0][
        "claim_token"
    ]
    assert (await alice.post(f"/guests/claim/{token}")).status_code == 409


async def test_only_the_host_sees_claim_links(make_device):
    alice, _gary, st = await _finished_game_guest_won(make_device)
    eve = await make_device("Eve")
    assert (await eve.get(f"/rooms/{st['room_id']}/guest-claims")).status_code == 403
    del alice
