"""Leaving a game that's already running.

The money is the delicate part: a player who walks out has still played,
so their balance has to survive and settle with everyone else's — unlike a
lobby leaver, who is forgotten entirely.
"""

from __future__ import annotations

RULES = {"card_value_cents": 100, "base_cards": 1}


async def _started(make_device, n):
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


async def _play_round(room_id, winner, losers, st):
    r = await winner.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    for i, p in enumerate(losers):
        r = await p.post(
            f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": i + 2}
        )
        st = r.json()
    return st


async def test_stepping_out_keeps_your_money_and_frees_you(make_device):
    room_id, (host, p1, p2), st = await _started(make_device, 3)
    st = await _play_round(room_id, host, [p1, p2], st)
    owed_before = st["balances"][p1.user_id]
    assert owed_before < 0  # P1 lost the round

    r = await p1.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()

    # Out of the game, but the money stays on the table.
    assert p1.user_id not in st["members"]
    assert st["balances"][p1.user_id] == owed_before
    assert st["status"] == "in_progress"  # two players left, game continues

    # No way back in — the engine refuses mid-game joins.
    assert (await p1.post(f"/rooms/{room_id}/join")).status_code == 400
    # ...but they're free to play elsewhere immediately.
    assert (await p1.post("/rooms")).status_code == 201


async def test_the_leaver_still_settles_and_keeps_their_history(make_device):
    room_id, (host, p1, p2), st = await _started(make_device, 3)
    st = await _play_round(room_id, host, [p1, p2], st)
    owed = st["balances"][p1.user_id]

    r = await p1.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    st = r.json()
    # The remaining two play on, then the host ends it.
    st = await _play_round(room_id, host, [p2], st)
    r = await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text

    # The leaver owes what they owed when they walked out, and the debt
    # names them properly rather than "Player".
    debts = (await p1.get("/debts/me")).json()
    assert len(debts["owing"]) == 1
    assert debts["owing"][0]["amount_cents"] == -owed
    host_debts = (await host.get("/debts/me")).json()
    assert "P1" in [d["counterparty_display_name"] for d in host_debts["owed"]]

    # The game they played is still theirs: history and stats keep it.
    games = (await p1.get("/history/me")).json()["games"]
    assert [g["room_id"] for g in games] == [room_id]
    facts = (await p1.get("/stats/facts")).json()["sessions"]
    assert len(facts) == 1
    # Credited with the one round they played, not the one after they left.
    assert facts[0]["taidi"]["rounds_played"] == 1
    assert (await host.get("/stats/facts")).json()["sessions"][0]["taidi"]["rounds_played"] == 2


async def test_stepping_out_mid_collection_restarts_the_round(make_device):
    room_id, (host, p1, p2), st = await _started(make_device, 3)
    r = await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    r = await p1.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 4})
    st = r.json()
    assert st["rounds"][-1]["phase"] == "collecting"

    # P2 walks out while the round is still waiting on them.
    r = await p2.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()
    # The round is put back rather than stranding the table forever.
    assert st["rounds"][-1]["phase"] == "playing"
    assert st["rounds"][-1]["winner"] is None
    assert st["balances"][p2.user_id] == 0
    del p1


async def test_last_two_becoming_one_ends_the_game(make_device):
    room_id, (host, p1), st = await _started(make_device, 2)
    st = await _play_round(room_id, host, [p1], st)

    r = await p1.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    # One player can't play Taidi, so the game settles instead of hanging.
    assert r.json()["status"] == "ended"
    assert len((await host.get("/debts/me")).json()["owed"]) == 1


async def test_host_stepping_out_hands_the_room_on(make_device):
    room_id, (host, p1, p2), st = await _started(make_device, 3)
    st = await _play_round(room_id, host, [p1, p2], st)

    r = await host.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["status"] == "in_progress"
    # Ending is host-only, so someone still there has to hold the title.
    assert st["host_id"] in (p1.user_id, p2.user_id)

    new_host = p1 if st["host_id"] == p1.user_id else p2
    r = await new_host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text


async def test_step_out_needs_a_game_in_progress(make_device):
    host = await make_device("Host")
    r = await host.post("/rooms")
    room_id = r.json()["room_id"]
    assert (
        await host.post(f"/rooms/{room_id}/step-out", json={"expected_seq": 0})
    ).status_code == 400
