"""Integration tests for the one-active-room-per-player limit and the lazy
staleness auto-close (see events_store.py's find_active_room/
ensure_no_other_active_room and _maybe_close_stale_room).
"""

from __future__ import annotations

from datetime import timedelta

from app.db import engine
from app.db import events as events_table
from app.db import rooms as rooms_table
from app.time import utcnow
from sqlalchemy import update


async def _backdate_room(room_id: str, *, hours: float) -> None:
    """Pushes every event's created_at (and the room seed's created_at, for
    a room with none yet) far enough into the past that the next rebuild
    sees it as stale, without waiting in real time."""
    cutoff = utcnow() - timedelta(hours=hours)
    async with engine.begin() as conn:
        await conn.execute(
            update(events_table).where(events_table.c.room_id == room_id).values(created_at=cutoff)
        )
        await conn.execute(
            update(rooms_table).where(rooms_table.c.room_id == room_id).values(created_at=cutoff)
        )


async def test_create_blocked_while_already_hosting_a_lobby(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    assert r.status_code == 201, r.text
    active_room_id = r.json()["room_id"]

    r = await alice.post("/rooms")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["active_room_id"] == active_room_id


async def test_create_blocked_while_already_hosting_an_in_progress_game(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/start", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    r = await alice.post("/rooms")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["active_room_id"] == room_id


async def test_create_allowed_after_disbanding(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    r = await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": 0})
    assert r.status_code == 200, r.text

    r = await alice.post("/rooms")
    assert r.status_code == 201, r.text


async def test_join_blocked_while_already_in_another_room(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")

    r = await alice.post("/rooms")
    room_a = r.json()["room_id"]
    invite_a = r.json()["invite_code"]
    await bob.post("/rooms")  # puts Bob in his own active lobby

    # Bob is already hosting his own lobby — joining Alice's room should be
    # rejected.
    await bob.get(f"/rooms/by-code/{invite_a}")
    r = await bob.post(f"/rooms/{room_a}/join")
    assert r.status_code == 409, r.text

    # Cara has no active room yet — joining works normally.
    await cara.get(f"/rooms/by-code/{invite_a}")
    r = await cara.post(f"/rooms/{room_a}/join")
    assert r.status_code == 200, r.text


async def test_leaving_a_lobby_frees_the_player_to_join_another(make_device):
    """room_participants keeps a row for anyone who has EVER joined (see
    ADR-0007), so the active-room check has to confirm current membership
    against the event log rather than trusting that index."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    cara = await make_device("Cara")

    r = await alice.post("/rooms")
    room_a, invite_a = r.json()["room_id"], r.json()["invite_code"]
    r = await cara.post("/rooms")
    room_c, invite_c = r.json()["room_id"], r.json()["invite_code"]

    await bob.get(f"/rooms/by-code/{invite_a}")
    r = await bob.post(f"/rooms/{room_a}/join")
    assert r.status_code == 200, r.text
    r = await bob.post(f"/rooms/{room_a}/leave", json={"expected_seq": r.json()["seq"]})
    assert r.status_code == 200, r.text

    await bob.get(f"/rooms/by-code/{invite_c}")
    r = await bob.post(f"/rooms/{room_c}/join")
    assert r.status_code == 200, r.text


async def test_host_disbanding_frees_them_to_create_another(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    r = await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": r.json()["seq"]})
    assert r.status_code == 200, r.text

    # Both the host and the joiner are freed by the disband.
    assert (await alice.post("/rooms")).status_code == 201
    assert (await bob.post("/rooms")).status_code == 201


async def test_active_room_endpoint_tracks_membership(make_device):
    """GET /rooms/active is how a player gets back into a live game from a
    device that has never seen its URL."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    assert (await alice.get("/rooms/active")).json()["room_id"] is None

    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]

    body = (await alice.get("/rooms/active")).json()
    assert body["room_id"] == room_id
    assert body["invite_code"] == invite
    assert body["game_type"] == "taidi"
    assert body["status"] == "lobby"

    # A joiner sees it too, and stops seeing it once they leave.
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    assert (await bob.get("/rooms/active")).json()["room_id"] == room_id
    await bob.post(f"/rooms/{room_id}/leave", json={"expected_seq": r.json()["seq"]})
    assert (await bob.get("/rooms/active")).json()["room_id"] is None

    # Still reported mid-game — that's the whole point of the rejoin path.
    r = await bob.post(f"/rooms/{room_id}/join")
    r = await alice.post(f"/rooms/{room_id}/start", json={"expected_seq": r.json()["seq"]})
    body = (await alice.get("/rooms/active")).json()
    assert body["room_id"] == room_id
    assert body["status"] == "in_progress"

    # ...and gone once the game is over.
    await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": r.json()["seq"]})
    assert (await alice.get("/rooms/active")).json()["room_id"] is None
    assert (await bob.get("/rooms/active")).json()["room_id"] is None


async def test_reading_a_stale_room_does_not_close_it(make_device):
    """Reads are pure — the backstop only runs where a stale room would
    actually block someone (find_active_room). Otherwise polling a lobby
    would disband it while someone sits watching it."""
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]

    await _backdate_room(room_id, hours=99)

    assert (await alice.get(f"/rooms/{room_id}/state")).json()["status"] == "lobby"
    assert (await alice.get("/history/me")).json()["games"] == []
    assert (await alice.get(f"/rooms/{room_id}/state")).json()["status"] == "lobby"


async def test_stale_lobby_auto_disbands_when_it_would_block(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]

    await _backdate_room(room_id, hours=13)  # past the 12h lobby threshold

    # The rejoin lookup runs find_active_room, which closes it.
    assert (await alice.get("/rooms/active")).json()["room_id"] is None
    assert (await alice.get(f"/rooms/{room_id}/state")).json()["status"] == "disbanded"

    # Freed up: Alice can host a new room instead of being locked out.
    assert (await alice.post("/rooms")).status_code == 201


async def test_fresh_lobby_is_not_closed(make_device):
    alice = await make_device("Alice")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]

    assert (await alice.get("/rooms/active")).json()["room_id"] == room_id
    assert (await alice.get(f"/rooms/{room_id}/state")).json()["status"] == "lobby"


async def test_stale_in_progress_game_auto_ends_and_settles(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/start",
        json={"expected_seq": state["seq"], "rules": {"card_value_cents": 100, "base_cards": 1}},
    )
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    state = r.json()
    r = await bob.post(f"/rooms/{room_id}/cards", json={"expected_seq": state["seq"], "cards": 1})
    assert r.status_code == 200, r.text

    await _backdate_room(room_id, hours=25)  # past the 24h in-progress threshold

    assert (await alice.get("/rooms/active")).json()["room_id"] is None
    assert (await alice.get(f"/rooms/{room_id}/state")).json()["status"] == "ended"

    a = (await alice.get("/debts/me")).json()
    assert len(a["owed"]) == 1
    assert a["owed"][0]["amount_cents"] == 200

    # Marked as the backstop's doing, not Alice's — she never pressed End.
    g = (await alice.get("/history/me")).json()["games"][0]
    assert g["auto_ended"] is True
    assert g["ended_by"] is None


async def test_stale_game_stuck_mid_collection_still_closes(make_device):
    """Taidi refuses to end a game while a round is collecting, and nothing
    in the UI can void it — so without the void-then-end fallback these
    players would be locked out of the app permanently."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(
        f"/rooms/{room_id}/start",
        json={"expected_seq": state["seq"], "rules": {"card_value_cents": 100, "base_cards": 1}},
    )
    state = r.json()
    # Alice claims the win; Bob never submits his card count.
    r = await alice.post(f"/rooms/{room_id}/win", json={"expected_seq": state["seq"]})
    assert r.json()["rounds"][-1]["phase"] == "collecting"

    # Confirm the game genuinely cannot be ended in this state.
    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": r.json()["seq"]})
    assert r.status_code == 400, r.text

    await _backdate_room(room_id, hours=25)

    assert (await bob.get("/rooms/active")).json()["room_id"] is None
    st = (await alice.get(f"/rooms/{room_id}/state")).json()
    assert st["status"] == "ended"
    # The unfinished round was voided, so nobody owes anything from it.
    assert (await alice.get("/debts/me")).json()["owed"] == []
    # Both players are free again.
    assert (await alice.post("/rooms")).status_code == 201
    assert (await bob.post("/rooms")).status_code == 201


async def test_player_ended_game_records_who_ended_it(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/start", json={"expected_seq": state["seq"]})
    # Taidi lets any member end the game — here Bob does, not the host.
    r = await bob.post(f"/rooms/{room_id}/end", json={"expected_seq": r.json()["seq"]})
    assert r.status_code == 200, r.text

    g = (await alice.get("/history/me")).json()["games"][0]
    assert g["auto_ended"] is False
    assert g["ended_by"] == "Bob"


async def test_fresh_in_progress_game_is_not_closed(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite = r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()
    r = await alice.post(f"/rooms/{room_id}/start", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    r = await alice.get(f"/rooms/{room_id}/state")
    assert r.json()["status"] == "in_progress"
