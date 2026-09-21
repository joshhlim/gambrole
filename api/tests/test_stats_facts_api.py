"""Integration tests for GET /stats/facts — the per-session counters the
stats page filters and aggregates client-side.
"""

from __future__ import annotations

TAIDI_RULES = {
    "card_value_cents": 100,
    "base_cards": 1,
    "double_threshold": 3,
    "triple_threshold": 5,
}


async def test_empty_when_no_games(make_device):
    alice = await make_device("Alice")
    r = await alice.get("/stats/facts")
    assert r.status_code == 200, r.text
    assert r.json()["sessions"] == []


async def test_taidi_session_carries_counters_and_opponents(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    st = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/start", json={"expected_seq": st["seq"], "rules": TAIDI_RULES}
    )
    st = r.json()
    # Alice wins with Bob left on 5 cards -> a triple for Bob, a trap for Alice.
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    r = await bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 5})
    st = r.json()
    await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})

    body = (await alice.get("/stats/facts")).json()
    assert len(body["sessions"]) == 1
    s = body["sessions"][0]
    assert s["game_type"] == "taidi"
    assert s["room_id"] == room_id
    assert s["mahjong"] is None
    assert [o["display_name"] for o in s["opponents"]] == ["Bob"]
    t = s["taidi"]
    assert t["rounds_played"] == 1
    assert t["rounds_won"] == 1
    assert t["trapping_wins"] == 1
    assert t["payer_rounds"] == 0
    assert s["net_cents"] > 0

    # Bob's mirror image: he paid, on a triple, and trapped nobody.
    tb = (await bob.get("/stats/facts")).json()["sessions"][0]["taidi"]
    assert tb["rounds_won"] == 0
    assert tb["payer_rounds"] == 1
    assert tb["triple_rounds"] == 1
    assert tb["trapping_wins"] == 0


async def test_mahjong_session_counters_including_concealed_and_shooting(make_device):
    alice = await make_device("Alice")
    others = [await make_device(n) for n in ("Bob", "Cara", "Dan")]

    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for d in others:
        await d.get(f"/rooms/by-code/{invite}")
        await d.post(f"/rooms/{room_id}/mahjong/join")
    st = (await alice.get(f"/rooms/{room_id}/state")).json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/start", json={"expected_seq": st["seq"], "rules": {}}
    )
    st = r.json()
    # An anyao and an angang, then a direct win off Bob (seat 1).
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/yao",
        json={"expected_seq": st["seq"], "target_seat": 0, "an": True},
    )
    st = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/gang", json={"expected_seq": st["seq"], "target": "angang"}
    )
    st = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={"expected_seq": st["seq"], "mode": "direct", "target_seat": 1, "tai": 1},
    )
    st = r.json()
    await alice.post(f"/rooms/{room_id}/mahjong/end", json={"expected_seq": st["seq"]})

    s = (await alice.get("/stats/facts")).json()["sessions"][0]
    assert s["game_type"] == "mahjong"
    assert s["taidi"] is None
    assert len(s["opponents"]) == 3
    m = s["mahjong"]
    # The concealed variants are the ones the fold used to throw away.
    assert m["anyao_count"] == 1 and m["yao_count"] == 0
    assert m["angang_count"] == 1 and m["gang_count"] == 0
    assert m["hands_won"] == 1 and m["direct_wins"] == 1 and m["zimo_wins"] == 0
    assert m["tai_wins"] == 1 and m["tai_total"] == 1

    # Bob shot the winning tile; Cara and Dan only paid the yao/gang.
    mb = (await others[0].get("/stats/facts")).json()["sessions"][0]["mahjong"]
    assert mb["lost_hands"] == 1 and mb["shot_hands"] == 1
    mc = (await others[1].get("/stats/facts")).json()["sessions"][0]["mahjong"]
    assert mc["shot_hands"] == 0


async def test_sessions_are_oldest_first_and_exclude_games_not_played(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")

    async def play(host, guest):
        r = await host.post("/rooms")
        room_id, invite = r.json()["room_id"], r.json()["invite_code"]
        await guest.get(f"/rooms/by-code/{invite}")
        r = await guest.post(f"/rooms/{room_id}/join")
        st = r.json()
        r = await host.post(
            f"/rooms/{room_id}/start", json={"expected_seq": st["seq"], "rules": TAIDI_RULES}
        )
        st = r.json()
        r = await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
        st = r.json()
        r = await guest.post(
            f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 1}
        )
        st = r.json()
        await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
        return room_id

    first = await play(alice, bob)
    second = await play(alice, cara)

    sessions = (await alice.get("/stats/facts")).json()["sessions"]
    assert [s["room_id"] for s in sessions] == [first, second]

    # Bob only played the first, so that's all he sees.
    bob_sessions = (await bob.get("/stats/facts")).json()["sessions"]
    assert [s["room_id"] for s in bob_sessions] == [first]


async def _befriend(a, b):
    await a.get("/users/me")
    await b.get("/users/me")
    await a.post("/friends/requests", json={"user_id": b.user_id})
    edge = (await b.get("/friends")).json()["incoming"][0]["id"]
    await b.post(f"/friends/requests/{edge}/accept")


async def _play(host, guest):
    r = await host.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await guest.get(f"/rooms/by-code/{invite}")
    r = await guest.post(f"/rooms/{room_id}/join")
    st = r.json()
    r = await host.post(
        f"/rooms/{room_id}/start", json={"expected_seq": st["seq"], "rules": TAIDI_RULES}
    )
    st = r.json()
    r = await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})
    st = r.json()
    r = await guest.post(f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "cards": 5})
    st = r.json()
    await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})


async def test_friend_stats_require_friendship(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    stranger = await make_device("Stranger")
    await _play(alice, bob)
    await stranger.get("/users/me")

    # Having played together is not access — only an accepted friendship is.
    assert (await bob.get(f"/stats/facts/{alice.user_id}")).status_code == 403
    assert (await stranger.get(f"/stats/facts/{alice.user_id}")).status_code == 403

    await _befriend(alice, bob)
    r = await bob.get(f"/stats/facts/{alice.user_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["player"]["display_name"] == "Alice"
    # Alice won, so her numbers are hers — not a copy of Bob's.
    assert body["sessions"][0]["net_cents"] > 0
    assert body["sessions"][0]["taidi"]["rounds_won"] == 1

    # A stranger still can't, and unfriending revokes it again.
    assert (await stranger.get(f"/stats/facts/{alice.user_id}")).status_code == 403
    await alice.delete(f"/friends/{bob.user_id}")
    assert (await bob.get(f"/stats/facts/{alice.user_id}")).status_code == 403


async def test_your_own_facts_need_no_friendship(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play(alice, bob)

    r = await alice.get(f"/stats/facts/{alice.user_id}")
    assert r.status_code == 200, r.text
    assert r.json()["player"]["display_name"] == "Alice"
    # Same payload as the unparameterised route.
    assert r.json()["sessions"] == (await alice.get("/stats/facts")).json()["sessions"]


async def test_a_pending_request_does_not_grant_access(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _play(alice, bob)
    await alice.get("/users/me")
    await bob.get("/users/me")
    await bob.post("/friends/requests", json={"user_id": alice.user_id})

    assert (await bob.get(f"/stats/facts/{alice.user_id}")).status_code == 403
