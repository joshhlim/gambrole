"""Groups: a regular crew with an invite code, games played "in" it, and a
leaderboard built from those games."""

from __future__ import annotations


async def _group(owner, name="Friday Night"):
    await owner.get("/users/me")
    r = await owner.post("/groups", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _join(device, group):
    await device.get("/users/me")
    r = await device.post(f"/groups/join/{group['invite_code'].lower()}")
    assert r.status_code == 200, r.text
    return r.json()


async def _taidi_game_in(group, host, others, *, guest=None):
    """host wins one round off everyone else; returns the ended room."""
    r = await host.post("/rooms", json={"group_id": group["group_id"]})
    assert r.status_code == 201, r.text
    room = r.json()
    room_id = room["room_id"]
    for d in others:
        await d.get(f"/rooms/by-code/{room['invite_code']}")
        room = (await d.post(f"/rooms/{room_id}/join")).json()
    guest_id = None
    if guest:
        room = (
            await host.post(
                f"/rooms/{room_id}/guests",
                json={"expected_seq": room["seq"], "display_name": guest},
            )
        ).json()
        guest_id = next(p for p, m in room["members"].items() if m["display_name"] == guest)
    st = (await host.post(f"/rooms/{room_id}/start", json={"expected_seq": room["seq"]})).json()
    st = (
        await host.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"], "round_no": 1})
    ).json()
    for d in others:
        st = (
            await d.post(
                f"/rooms/{room_id}/cards",
                json={"expected_seq": st["seq"], "round_no": 1, "cards": 3},
            )
        ).json()
    if guest_id:
        st = (
            await host.post(
                f"/rooms/{room_id}/cards",
                json={"expected_seq": st["seq"], "round_no": 1, "cards": 3, "as_player": guest_id},
            )
        ).json()
    r = await host.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    return r.json(), guest_id


async def test_create_join_and_list(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    group = await _group(alice)
    assert group["name"] == "Friday Night" and len(group["members"]) == 1
    group = await _join(bob, group)
    assert {m["user_id"] for m in group["members"]} == {alice.user_id, bob.user_id}
    # Joining twice is harmless.
    assert len((await _join(bob, group))["members"]) == 2

    listed = (await bob.get("/groups")).json()["groups"]
    assert [(g["name"], g["member_count"], g["is_owner"]) for g in listed] == [
        ("Friday Night", 2, False)
    ]


async def test_outsiders_see_nothing(make_device):
    alice, eve = await make_device("Alice"), await make_device("Eve")
    group = await _group(alice)
    await eve.get("/users/me")
    assert (await eve.get(f"/groups/{group['group_id']}")).status_code == 403
    r = await eve.post("/rooms", json={"group_id": group["group_id"]})
    assert r.status_code == 403


async def test_leaderboard_from_group_games_including_claimed_guests(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    group = await _group(alice)
    await _join(bob, group)

    room, guest_id = await _taidi_game_in(group, alice, [bob], guest="Gary")
    await _taidi_game_in(group, alice, [bob])
    # A game outside the group doesn't count.
    await bob.post("/rooms")

    detail = (await alice.get(f"/groups/{group['group_id']}")).json()
    board = {row["display_name"]: row for row in detail["leaderboard"]}
    assert board["Alice"]["sessions"] == 2 and board["Alice"]["wins"] == 2
    assert board["Bob"]["net_cents"] < 0
    assert board["Gary"]["sessions"] == 1 and board["Gary"]["profile"] is None
    assert detail["leaderboard"][0]["display_name"] == "Alice"
    assert len(detail["recent_games"]) == 2
    assert sum(net for _name, net in detail["recent_games"][0]["results"]) == 0

    # Gary claims his game: the leaderboard now shows his account.
    token = (await alice.get(f"/rooms/{room['room_id']}/guest-claims")).json()["guests"][0][
        "claim_token"
    ]
    gareth = await make_device("Gareth")
    assert (await gareth.post(f"/guests/claim/{token}")).status_code == 200
    detail = (await alice.get(f"/groups/{group['group_id']}")).json()
    gareth_row = next(r for r in detail["leaderboard"] if r["player_id"] == gareth.user_id)
    assert gareth_row["display_name"] == "Gareth" and gareth_row["profile"] is not None
    del guest_id


async def test_owner_controls(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    group = await _group(alice)
    await _join(bob, group)
    gid = group["group_id"]

    assert (
        await bob._client.patch(f"/groups/{gid}", headers=bob._headers, json={"name": "X"})
    ).status_code == 403
    r = await alice._client.patch(
        f"/groups/{gid}", headers=alice._headers, json={"name": "  Sunday  Crew "}
    )
    assert r.json()["name"] == "Sunday Crew"

    old_code = group["invite_code"]
    new_code = (await alice.post(f"/groups/{gid}/invite-code")).json()["invite_code"]
    assert new_code != old_code
    assert (await (await make_device("Late")).post(f"/groups/join/{old_code}")).status_code == 404

    r = await alice.delete(f"/groups/{gid}/members/{bob.user_id}")
    assert [m["user_id"] for m in r.json()["members"]] == [alice.user_id]


async def test_owner_leaving_hands_over_or_closes(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    group = await _group(alice)
    await _join(bob, group)
    gid = group["group_id"]
    await alice.post(f"/groups/{gid}/leave")
    detail = (await bob.get(f"/groups/{gid}")).json()
    assert detail["owner_id"] == bob.user_id

    await bob.post(f"/groups/{gid}/leave")
    assert (await bob.get(f"/groups/{gid}")).status_code == 404


async def test_rooms_carry_their_group(make_device):
    alice = await make_device("Alice")
    group = await _group(alice)
    room = (await alice.post("/rooms", json={"group_id": group["group_id"]})).json()
    assert room["group_id"] == group["group_id"]
    state = (await alice.get(f"/rooms/{room['room_id']}/state")).json()
    assert state["group_id"] == group["group_id"]
