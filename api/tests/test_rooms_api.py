"""End-to-end tests against the real API + a real Postgres database.

Each test drives the room through HTTP exactly as the frontend will: one
`Device` per player, bearer-authenticated, no shortcuts through taidi_core
directly. This is what actually proves the "live room on two phones" slice
works, not just that the pure state machine does.
"""

from __future__ import annotations


async def _create_room(host) -> tuple[str, str]:
    r = await host.post("/rooms")
    assert r.status_code == 201, r.text
    body = r.json()
    return body["room_id"], body["invite_code"]


async def test_create_room_defaults_to_taidi_game_type(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    assert r.status_code == 201, r.text
    assert r.json()["game_type"] == "taidi"


async def test_create_room_accepts_explicit_game_type(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["game_type"] == "mahjong"

    room_id = body["room_id"]
    r = await alice.get(f"/rooms/{room_id}/state")
    assert r.json()["game_type"] == "mahjong"


async def test_create_room_seeds_host_as_first_member(make_device):
    alice = await make_device("Alice")
    room_id, invite_code = await _create_room(alice)
    assert len(invite_code) == 6

    r = await alice.get(f"/rooms/{room_id}/state")
    assert r.status_code == 200
    state = r.json()
    assert state["status"] == "lobby"
    assert alice.user_id in state["members"]
    assert state["host_id"] == alice.user_id


async def test_join_by_invite_code(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)

    r = await bob.post(f"/rooms/by-code/{invite_code}")
    assert r.status_code == 405  # GET-only lookup, no POST
    r = await bob.get(f"/rooms/by-code/{invite_code}")
    assert r.status_code == 200
    assert r.json()["room_id"] == room_id

    r = await bob.post(f"/rooms/{room_id}/join")
    assert r.status_code == 200, r.text
    state = r.json()
    assert bob.user_id in state["members"]
    assert len(state["members"]) == 2


async def test_full_game_across_three_devices(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    charlie = await make_device("Charlie")
    room_id, invite_code = await _create_room(alice)

    for device in (bob, charlie):
        r = await device.get(f"/rooms/by-code/{invite_code}")
        rid = r.json()["room_id"]
        r = await device.post(f"/rooms/{rid}/join")
        assert r.status_code == 200, r.text

    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert len(state["members"]) == 3

    r = await alice.post(
        f"/rooms/{room_id}/start",
        json={"expected_seq": state["seq"], "rules": {"card_value_cents": 100}},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["status"] == "in_progress"

    # Alice wins round 1: Bob=3, Charlie=11
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["rounds"][0]["phase"] == "collecting"

    r = await bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 3})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["rounds"][0]["phase"] == "collecting"  # Charlie hasn't submitted yet

    r = await charlie.post(
        f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 11}
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["rounds"][0]["phase"] == "resolved"
    assert len(state["rounds"]) == 2
    balances = {k: v for k, v in state["balances"].items()}
    assert sum(balances.values()) == 0
    assert balances[alice.user_id] > 0

    # Bob claims a special hand mid-round-2
    r = await bob.post(f"/rooms/{room_id}/special", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    state = r.json()
    assert sum(state["balances"].values()) == 0

    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["status"] == "ended"


async def test_stale_seq_returns_409_with_current_state(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)
    await bob.get(f"/rooms/by-code/{invite_code}")
    await bob.post(f"/rooms/{room_id}/join")

    r = await alice.post(f"/rooms/{room_id}/start", json={"expected_seq": 999, "rules": {}})
    assert r.status_code == 409
    assert "state" in r.json()["detail"]


async def test_only_host_can_start(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)
    await bob.get(f"/rooms/by-code/{invite_code}")
    await bob.post(f"/rooms/{room_id}/join")
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await bob.post(f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}})
    assert r.status_code == 403


async def test_double_win_claim_returns_400(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)
    await bob.get(f"/rooms/by-code/{invite_code}")
    await bob.post(f"/rooms/{room_id}/join")
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()
    state = (await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})).json()

    r = await bob.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    assert r.status_code == 400


async def test_unauthenticated_request_is_rejected(client):
    r = await client.post("/rooms")
    assert r.status_code == 401


async def test_unknown_room_returns_404(make_device):
    alice = await make_device("Alice")
    r = await alice.get("/rooms/00000000-0000-0000-0000-000000000000/state")
    assert r.status_code == 404


async def test_concurrent_card_submissions_do_not_corrupt_state(make_device):
    """Two players submit their card counts 'at the same time' — both should
    land (different targets), and the round should still resolve exactly once."""
    import asyncio

    alice = await make_device("Alice")
    bob = await make_device("Bob")
    charlie = await make_device("Charlie")
    room_id, invite_code = await _create_room(alice)
    for d in (bob, charlie):
        await d.get(f"/rooms/by-code/{invite_code}")
        await d.post(f"/rooms/{room_id}/join")
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()
    state = (await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})).json()

    results = await asyncio.gather(
        bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 3}),
        charlie.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 11}),
    )
    codes = sorted(r.status_code for r in results)
    # One of them submitted against a stale seq (the other landed first) and gets 409,
    # or FastAPI's dispatch retry let both land — either way, exactly one round resolves.
    assert codes in ([200, 200], [200, 409])

    final = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert sum(final["balances"].values()) == 0
    if codes == [200, 409]:
        # the loser must retry with the fresh seq to actually submit
        retry_target = bob if results[0].status_code == 409 else charlie
        cards = 3 if retry_target is bob else 11
        r = await retry_target.post(
            f"/rooms/{room_id}/cards", json={"expected_seq": final["seq"], "cards": cards}
        )
        assert r.status_code == 200, r.text
        final = r.json()
    assert final["rounds"][0]["phase"] == "resolved"


async def _four_player_round_collecting(make_device):
    alice = await make_device("Alice")
    others = [await make_device(n) for n in ("Bob", "Charlie", "Dana")]
    room_id, invite_code = await _create_room(alice)
    for d in others:
        await d.get(f"/rooms/by-code/{invite_code}")
        await d.post(f"/rooms/{room_id}/join")
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()
    state = (await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})).json()
    return alice, others, room_id, state


async def test_card_submissions_naming_the_round_all_land_when_simultaneous(make_device):
    """Regression: every loser submitting against the same seq used to race,
    and whoever lost twice had their submit bounce. Naming the round instead
    lets them all land, and the round resolves exactly once."""
    import asyncio

    alice, others, room_id, state = await _four_player_round_collecting(make_device)
    results = await asyncio.gather(
        *(
            d.post(
                f"/rooms/{room_id}/cards",
                json={"expected_seq": state["seq"], "round_no": 1, "cards": 3 + i},
            )
            for i, d in enumerate(others)
        )
    )
    assert [r.status_code for r in results] == [200, 200, 200], [r.text for r in results]

    final = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert final["rounds"][0]["phase"] == "resolved"
    assert final["rounds"][0]["cards_submitted"] == {d.user_id: 3 + i for i, d in enumerate(others)}
    assert len(final["rounds"]) == 2
    assert sum(final["balances"].values()) == 0


async def test_card_submission_for_a_past_round_is_refused(make_device):
    _alice, others, room_id, state = await _four_player_round_collecting(make_device)
    r = await others[0].post(
        f"/rooms/{room_id}/cards",
        json={"expected_seq": state["seq"], "round_no": 2, "cards": 3},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["state"]["seq"] == state["seq"]


async def test_invite_code_present_on_every_response_not_just_create(make_device):
    """Regression: invite_code must be visible to any member at any time, not
    just in the create-room response — the frontend lobby reads it from
    whichever response it last received."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)

    r = await alice.get(f"/rooms/{room_id}/state")
    assert r.json()["invite_code"] == invite_code

    await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/join")
    assert r.json()["invite_code"] == invite_code

    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    r = await alice.post(
        f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    assert r.json()["invite_code"] == invite_code


async def test_member_can_leave_lobby(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)
    await bob.get(f"/rooms/by-code/{invite_code}")
    state = (await bob.post(f"/rooms/{room_id}/join")).json()

    r = await bob.post(f"/rooms/{room_id}/leave", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    assert bob.user_id not in r.json()["members"]


async def test_host_cannot_leave_returns_400(make_device):
    alice = await make_device("Alice")
    room_id, invite_code = await _create_room(alice)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await alice.post(f"/rooms/{room_id}/leave", json={"expected_seq": state["seq"]})
    assert r.status_code == 400


async def test_host_can_disband_lobby(make_device):
    alice = await make_device("Alice")
    room_id, invite_code = await _create_room(alice)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disbanded"


async def test_non_host_cannot_disband(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_room(alice)
    await bob.get(f"/rooms/by-code/{invite_code}")
    state = (await bob.post(f"/rooms/{room_id}/join")).json()

    r = await bob.post(f"/rooms/{room_id}/disband", json={"expected_seq": state["seq"]})
    assert r.status_code == 403
