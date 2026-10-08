"""End-to-end tests against the real API + a real Postgres database, for the
Mahjong endpoints. Mirrors test_rooms_api.py's shape and philosophy — one
Device per player, bearer-authenticated, no shortcuts through mahjong_core
directly.
"""

from __future__ import annotations


async def _create_mahjong_room(host) -> tuple[str, str]:
    r = await host.post("/rooms", json={"game_type": "mahjong"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["game_type"] == "mahjong"
    return body["room_id"], body["invite_code"]


async def _join_all(room_id: str, invite_code: str, devices) -> None:
    for d in devices:
        r = await d.get(f"/rooms/by-code/{invite_code}")
        assert r.status_code == 200, r.text
        r = await d.post(f"/rooms/{room_id}/mahjong/join")
        assert r.status_code == 200, r.text


async def _full_table(make_device) -> tuple[str, str, list]:
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")
    dan = await make_device("Dan")
    room_id, invite_code = await _create_mahjong_room(alice)
    await _join_all(room_id, invite_code, [bob, cara, dan])
    return room_id, invite_code, [alice, bob, cara, dan]


async def test_join_requires_exactly_four_to_start(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert len(state["members"]) == 4

    r = await alice.post(
        f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"


async def test_start_rejected_with_fewer_than_four(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_mahjong_room(alice)
    await _join_all(room_id, invite_code, [bob])
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await alice.post(
        f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    assert r.status_code == 400


# Amounts are cents. The arithmetic below is written in the old $0.50
# chips (yao 2, tai(1) hu 4, ...) times CHIP, which keeps it readable and
# doubles as a check that the 3/6 半 defaults are the same money as before.
CHIP = 50


async def test_yao_gang_hu_settle_correctly(make_device):
    """Uses the default rules (the "3/6 半" preset: yao=$1, gang=$1, tai(1)=hu/zimo $2)
    except yao/gang set explicitly for clearer arithmetic — the tai_table
    itself is exercised by test_mahjong_rules_fixtures.py."""
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start",
            json={
                "expected_seq": state["seq"],
                "rules": {"yao_amount": 100, "gang_amount": 100},
            },
        )
    ).json()

    # Alice YAOs herself: each of the other 3 pays 2.
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/yao",
        json={"expected_seq": state["seq"], "target_seat": 0, "an": False},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][alice.user_id] == (6) * CHIP
    assert state["balances"][bob.user_id] == (-2) * CHIP

    # Bob GANGs on Cara (seat 2): Cara alone pays 3x.
    r = await bob.post(
        f"/rooms/{room_id}/mahjong/gang", json={"expected_seq": state["seq"], "target": 2}
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][bob.user_id] == (-2 + 6) * CHIP
    assert state["balances"][cara.user_id] == (-2 - 6) * CHIP  # Cara already paid Alice's YAO
    assert state["hands"][0]["had_gang"] is True

    # Dan directly HUs off Alice (seat 0) at 1 tai: Alice pays the default
    # table's hu(1) = 4.
    r = await dan.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={"expected_seq": state["seq"], "mode": "direct", "target_seat": 0, "tai": 1},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][dan.user_id] == (-2 + 4) * CHIP  # Dan already paid Alice's YAO
    assert state["hands"][0]["closed"] is True
    # Dan (seat 3) isn't the dealer (seat 0) -> dealer rotates to seat 1 (Bob).
    assert len(state["hands"]) == 2
    assert state["hands"][1]["dealer_seat"] == 1


async def test_zimo_bonus_and_klppdd_settle_correctly(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start",
            json={
                "expected_seq": state["seq"],
                "rules": {"zimo_bonus_amount": 250, "klppdd_amount": 500},
            },
        )
    ).json()

    # Alice self-draws at 1 tai (hu(1)=4/zimo(1)=4) with both bonuses on:
    # each of the other 3 pays 4 + 5 + 10 = 19.
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={
            "expected_seq": state["seq"],
            "mode": "zimo",
            "target_seat": None,
            "tai": 1,
            "zimo_bonus": True,
            "klppdd": True,
        },
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][alice.user_id] == (19 * 3) * CHIP
    assert state["balances"][bob.user_id] == (-19) * CHIP

    # Dan HUs directly off Bob (seat 1) at 1 tai with klppdd on: Bob alone
    # pays hu(1)=4 + 3*10 klppdd = 34.
    r = await dan.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={
            "expected_seq": state["seq"],
            "mode": "direct",
            "target_seat": 1,
            "tai": 1,
            "klppdd": True,
        },
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][dan.user_id] == (-19 + 34) * CHIP
    assert state["balances"][bob.user_id] == (-19 - 34) * CHIP


async def test_zimo_bonus_rejected_on_direct_win(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start",
            json={"expected_seq": state["seq"], "rules": {"zimo_bonus_amount": 250}},
        )
    ).json()

    r = await dan.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={
            "expected_seq": state["seq"],
            "mode": "direct",
            "target_seat": 1,
            "tai": 1,
            "zimo_bonus": True,
        },
    )
    assert r.status_code == 400


async def test_no_win_repeats_dealer_when_no_gang(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()

    r = await alice.post(f"/rooms/{room_id}/mahjong/no-win", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    state = r.json()
    assert len(state["hands"]) == 2
    assert state["hands"][1]["dealer_seat"] == 0
    assert state["hands"][1]["wind"] == 1


async def test_assign_seats_reorders_before_start(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    seat_map = {alice.user_id: 3, bob.user_id: 2, cara.user_id: 1, dan.user_id: 0}
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/assign-seats",
        json={"expected_seq": state["seq"], "seat_map": seat_map},
    )
    assert r.status_code == 200, r.text
    members = r.json()["members"]
    assert members[alice.user_id]["seat"] == 3
    assert members[dan.user_id]["seat"] == 0


async def test_only_host_can_assign_seats(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await bob.post(
        f"/rooms/{room_id}/mahjong/assign-seats",
        json={
            "expected_seq": state["seq"],
            "seat_map": {alice.user_id: 0, bob.user_id: 1, cara.user_id: 2, dan.user_id: 3},
        },
    )
    assert r.status_code == 403


async def test_only_host_can_end_game(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()

    r = await bob.post(f"/rooms/{room_id}/mahjong/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 403

    r = await alice.post(f"/rooms/{room_id}/mahjong/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"


async def test_leave_and_disband_lobby(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    room_id, invite_code = await _create_mahjong_room(alice)
    await _join_all(room_id, invite_code, [bob])
    state = (await bob.get(f"/rooms/{room_id}/state")).json()

    r = await bob.post(f"/rooms/{room_id}/mahjong/leave", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    assert bob.user_id not in r.json()["members"]

    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    r = await alice.post(f"/rooms/{room_id}/mahjong/disband", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disbanded"


async def test_taidi_endpoint_rejects_mahjong_room(make_device):
    alice = await make_device("Alice")
    room_id, _invite_code = await _create_mahjong_room(alice)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    assert r.status_code == 400


async def test_mahjong_endpoint_rejects_taidi_room(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    state = (await alice.get(f"/rooms/{room_id}/state")).json()

    r = await alice.post(
        f"/rooms/{room_id}/mahjong/yao",
        json={"expected_seq": state["seq"], "target_seat": 0, "an": False},
    )
    assert r.status_code == 400


async def test_final_hand_win_sets_pending_then_continue_wind(make_device):
    room_id, invite_code, (alice, bob, cara, dan) = await _full_table(make_device)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    state = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/start", json={"expected_seq": state["seq"], "rules": {}}
        )
    ).json()

    # Gang + no-win 15 times to walk the dealer to wind 4, seat 3 (北).
    for _ in range(15):
        state = (
            await alice.post(
                f"/rooms/{room_id}/mahjong/gang",
                json={"expected_seq": state["seq"], "target": "angang"},
            )
        ).json()
        state = (
            await alice.post(
                f"/rooms/{room_id}/mahjong/no-win", json={"expected_seq": state["seq"]}
            )
        ).json()
    assert state["hands"][-1]["wind"] == 4
    assert state["hands"][-1]["dealer_seat"] == 3

    r = await dan.post(
        f"/rooms/{room_id}/mahjong/hu",
        json={"expected_seq": state["seq"], "mode": "direct", "target_seat": 1, "tai": 1},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["pending_wind_decision"] is True

    r = await alice.post(
        f"/rooms/{room_id}/mahjong/continue-wind", json={"expected_seq": state["seq"]}
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["pending_wind_decision"] is False
    assert state["hands"][-1]["wind"] == 5
    assert state["hands"][-1]["dealer_seat"] == 0
