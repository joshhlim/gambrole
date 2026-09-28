"""API behaviours added in the 2026-09-28 hardening pass: commands pinned
to a round/hand, rules saved at creation, room visibility, input limits,
active-room robustness, friendship races and rate limiting."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.config import settings
from app.db import engine
from app.db import events as events_table
from app.db import rooms as rooms_table
from app.time import utcnow
from sqlalchemy import insert, update


async def _taidi_game(make_device, n=3, rules=None):
    devices = [await make_device(name) for name in ("Alice", "Bob", "Cara", "Dan")[:n]]
    host = devices[0]
    body = {"rules": rules} if rules is not None else {}
    r = await host.post("/rooms", json=body)
    assert r.status_code == 201, r.text
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for d in devices[1:]:
        await d.get(f"/rooms/by-code/{invite}")
        r = await d.post(f"/rooms/{room_id}/join")
        assert r.status_code == 200, r.text
    st = r.json() if n > 1 else (await host.get(f"/rooms/{room_id}/state")).json()
    r = await host.post(f"/rooms/{room_id}/start", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    return room_id, devices, r.json()


async def _mahjong_game(make_device):
    devices = [await make_device(name) for name in ("Alice", "Bob", "Cara", "Dan")]
    host = devices[0]
    r = await host.post("/rooms", json={"game_type": "mahjong"})
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for d in devices[1:]:
        await d.get(f"/rooms/by-code/{invite}")
        r = await d.post(f"/rooms/{room_id}/mahjong/join")
    st = r.json()
    r = await host.post(f"/rooms/{room_id}/mahjong/start", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    return room_id, devices, r.json()


# ---------- pinned commands ----------


async def test_undo_pinned_to_a_round_that_already_paid_out_is_refused(make_device):
    """The host taps Undo while the last card count lands. Retrying that
    undo against the fresh seq used to void the round that had just paid
    out; pinned to the round it was about, it's refused instead."""
    room_id, (alice, bob, cara), st = await _taidi_game(make_device)
    st = (await bob.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})).json()
    seen = st
    await alice.post(
        f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "round_no": 1, "cards": 3}
    )
    await cara.post(
        f"/rooms/{room_id}/cards", json={"expected_seq": seen["seq"], "round_no": 1, "cards": 5}
    )
    r = await alice.post(
        f"/rooms/{room_id}/void", json={"expected_seq": seen["seq"], "round_no": 1}
    )
    assert r.status_code == 409, r.text
    state = r.json()["detail"]["state"]
    assert state["rounds"][0]["phase"] == "resolved"
    assert state["balances"][bob.user_id] > 0


async def test_undo_pinned_to_the_collecting_round_still_works_after_a_card_lands(make_device):
    room_id, (alice, bob, cara), st = await _taidi_game(make_device)
    st = (await bob.post(f"/rooms/{room_id}/win", json={"expected_seq": st["seq"]})).json()
    seen = st
    await alice.post(
        f"/rooms/{room_id}/cards", json={"expected_seq": st["seq"], "round_no": 1, "cards": 3}
    )
    r = await alice.post(
        f"/rooms/{room_id}/void", json={"expected_seq": seen["seq"], "round_no": 1}
    )
    assert r.status_code == 200, r.text
    assert r.json()["rounds"][0]["phase"] == "playing"
    del cara


async def test_two_no_wins_on_the_same_hand_close_only_that_hand(make_device):
    room_id, (alice, bob, _cara, _dan), st = await _mahjong_game(make_device)
    body = {"expected_seq": st["seq"], "hand_no": 1}
    first, second = await asyncio.gather(
        alice.post(f"/rooms/{room_id}/mahjong/no-win", json=body),
        bob.post(f"/rooms/{room_id}/mahjong/no-win", json=body),
    )
    codes = sorted([first.status_code, second.status_code])
    assert codes[0] == 200, (first.text, second.text)
    assert codes[1] in (400, 409), (first.text, second.text)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert len(state["hands"]) == 2 and not state["hands"][-1]["closed"]


async def test_independent_declarations_on_the_same_hand_both_land(make_device):
    room_id, (alice, bob, _cara, _dan), st = await _mahjong_game(make_device)
    yao, gang = await asyncio.gather(
        alice.post(
            f"/rooms/{room_id}/mahjong/yao",
            json={"expected_seq": st["seq"], "hand_no": 1, "target_seat": 2},
        ),
        bob.post(
            f"/rooms/{room_id}/mahjong/gang",
            json={"expected_seq": st["seq"], "hand_no": 1, "target": "angang"},
        ),
    )
    assert yao.status_code == 200 and gang.status_code == 200, (yao.text, gang.text)
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert len(state["hands"][0]["declarations"]) == 2


async def test_partial_seat_swap(make_device):
    devices = [await make_device(name) for name in ("Alice", "Bob", "Cara", "Dan")]
    alice, bob = devices[0], devices[1]
    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for d in devices[1:]:
        await d.get(f"/rooms/by-code/{invite}")
        r = await d.post(f"/rooms/{room_id}/mahjong/join")
    st = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/assign-seats",
        json={"expected_seq": st["seq"], "seat_map": {alice.user_id: 1, bob.user_id: 0}},
    )
    assert r.status_code == 200, r.text
    seats = {pid: m["seat"] for pid, m in r.json()["members"].items()}
    assert seats[alice.user_id] == 1 and seats[bob.user_id] == 0


# ---------- rules saved at creation ----------


async def test_rules_chosen_at_creation_apply_when_start_sends_none(make_device):
    room_id, (alice, _bob), st = await _taidi_game(
        make_device, n=2, rules={"card_value_cents": 100, "base_cards": 0}
    )
    assert st["rules"]["card_value_cents"] == 100
    assert st["draft_rules"]["card_value_cents"] == 100
    del alice, room_id


async def test_invalid_rules_at_creation_are_rejected(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms", json={"rules": {"card_value_cents": -5}})
    assert r.status_code == 422, r.text
    r = await alice.post("/rooms", json={"game_type": "mahjong", "rules": {"max_tai": 10**7}})
    assert r.status_code == 422, r.text


# ---------- visibility ----------


async def test_a_stranger_cant_read_a_game_in_progress(make_device):
    room_id, _devices, _st = await _taidi_game(make_device, n=2)
    eve = await make_device("Eve")
    r = await eve.get(f"/rooms/{room_id}/state")
    assert r.status_code == 403


async def test_a_lobby_is_readable_by_link(make_device):
    alice = await make_device("Alice")
    room_id = (await alice.post("/rooms")).json()["room_id"]
    eve = await make_device("Eve")
    assert (await eve.get(f"/rooms/{room_id}/state")).status_code == 200


async def test_someone_who_stepped_out_can_still_see_the_game(make_device):
    room_id, (alice, bob, cara), st = await _taidi_game(make_device)
    r = await cara.post(f"/rooms/{room_id}/step-out", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    assert (await cara.get(f"/rooms/{room_id}/state")).status_code == 200
    del alice, bob


# ---------- active-room robustness ----------


async def test_a_room_that_cant_be_replayed_doesnt_lock_its_members_out(make_device):
    alice = await make_device("Alice")
    room_id = (await alice.post("/rooms")).json()["room_id"]
    async with engine.begin() as conn:
        await conn.execute(
            insert(events_table).values(
                id="00000000-0000-0000-0000-00000000beef",
                room_id=room_id,
                seq=1,
                type="not_a_real_event",
                actor=None,
                payload={},
                created_at=utcnow(),
            )
        )
    assert (await alice.get("/rooms/active")).json() == {"room_id": None}
    assert (await alice.post("/rooms")).status_code == 201


async def test_a_stale_status_column_is_corrected(make_device):
    """Rooms from before rooms.status existed read 'lobby' until backfilled."""
    room_id, (alice, _bob), st = await _taidi_game(make_device, n=2)
    await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": st["seq"]})
    async with engine.begin() as conn:
        await conn.execute(
            update(rooms_table).where(rooms_table.c.room_id == room_id).values(status="lobby")
        )
    assert (await alice.get("/rooms/active")).json() == {"room_id": None}
    async with engine.connect() as conn:
        row = (
            await conn.execute(rooms_table.select().where(rooms_table.c.room_id == room_id))
        ).first()
    assert row.status == "ended"


async def test_two_members_closing_the_same_stale_room_at_once(make_device):
    room_id, (alice, bob), _st = await _taidi_game(make_device, n=2)
    cutoff = utcnow() - timedelta(hours=settings.in_progress_stale_hours + 1)
    async with engine.begin() as conn:
        await conn.execute(
            update(events_table).where(events_table.c.room_id == room_id).values(created_at=cutoff)
        )
    a, b = await asyncio.gather(alice.get("/rooms/active"), bob.get("/rooms/active"))
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    assert a.json() == b.json() == {"room_id": None}


# ---------- friendships ----------


async def test_simultaneous_mutual_requests_make_one_friendship(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    await alice.get("/users/me")
    await bob.get("/users/me")
    a, b = await asyncio.gather(
        alice.post("/friends/requests", json={"user_id": bob.user_id}),
        bob.post("/friends/requests", json={"user_id": alice.user_id}),
    )
    assert {a.status_code, b.status_code} <= {200, 201}, (a.text, b.text)
    friends = (await alice.get("/friends")).json()
    assert [f["user"]["user_id"] for f in friends["friends"]] == [bob.user_id]
    assert friends["incoming"] == [] and friends["outgoing"] == []

    assert (await alice.delete(f"/friends/{bob.user_id}")).status_code in (200, 204)
    assert (await bob.get("/friends")).json()["friends"] == []


async def test_accepting_a_withdrawn_request_is_a_404(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    await alice.get("/users/me")
    await bob.get("/users/me")
    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    edge = (await bob.get("/friends")).json()["incoming"][0]["id"]
    await alice.delete(f"/friends/requests/{edge}")
    assert (await bob.post(f"/friends/requests/{edge}/accept")).status_code == 404


async def test_two_people_claiming_one_handle_at_once(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    await alice.get("/users/me")
    await bob.get("/users/me")
    a, b = await asyncio.gather(
        alice.put("/users/me/username", json={"username": "samehandle"}),
        bob.put("/users/me/username", json={"username": "samehandle"}),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409], (a.text, b.text)


# ---------- limits and plumbing ----------


async def test_invite_code_guessing_is_rate_limited(make_device, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    alice = await make_device("Alice")
    codes = [(await alice.get(f"/rooms/by-code/ZZZZ{i:02d}")).status_code for i in range(35)]
    assert codes[0] == 404
    assert 429 in codes


async def test_oversized_request_body_is_refused(client):
    r = await client.post(
        "/rooms", content=b"{" + b" " * 70_000 + b"}", headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413


async def test_dev_login_rejects_an_overlong_name(client):
    r = await client.post("/auth/dev-login", json={"display_name": "x" * 101})
    assert r.status_code == 422


async def test_readiness_touches_the_database(client):
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
