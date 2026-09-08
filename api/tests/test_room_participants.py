"""Integration tests for the stats read-model added alongside the analytics
dashboard (ADR-0007): `rooms.status`/`.ended_at` kept in sync with the event
log, and `room_participants` indexing who has joined which room (excluding
the host, who never emits a player_joined event). Both are populated inside
`events_store.append_events()`, so these tests exercise them purely through
the existing HTTP endpoints — no direct calls into events_store.
"""

from __future__ import annotations

from uuid import UUID

from app.db import engine
from app.db import room_participants as room_participants_table
from app.db import rooms as rooms_table
from sqlalchemy import select


async def _room_row(room_id: str):
    async with engine.begin() as conn:
        result = await conn.execute(
            select(rooms_table.c.status, rooms_table.c.ended_at).where(
                rooms_table.c.room_id == UUID(room_id)
            )
        )
        return result.first()


async def _participant_ids(room_id: str) -> set[str]:
    async with engine.begin() as conn:
        result = await conn.execute(
            select(room_participants_table.c.player_id).where(
                room_participants_table.c.room_id == UUID(room_id)
            )
        )
        return {str(row.player_id) for row in result.all()}


async def test_join_populates_participants_but_not_host(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite_code = r.json()["invite_code"]

    row = await _room_row(room_id)
    assert row.status == "lobby"
    assert row.ended_at is None
    assert await _participant_ids(room_id) == set()

    await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/join")
    assert r.status_code == 200, r.text

    participants = await _participant_ids(room_id)
    assert participants == {bob.user_id}
    assert alice.user_id not in participants


async def test_mahjong_join_also_populates_participants(make_device):
    """The append_events hook is game-type-agnostic — spot-check Mahjong too."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms", json={"game_type": "mahjong"})
    room_id = r.json()["room_id"]
    invite_code = r.json()["invite_code"]

    await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/mahjong/join")
    assert r.status_code == 200, r.text

    assert await _participant_ids(room_id) == {bob.user_id}


async def test_leave_then_rejoin_does_not_duplicate_or_error(make_device):
    """Bob can leave and rejoin the same lobby, producing a second
    player_joined event for the same (room_id, player_id) — exercises the
    ON CONFLICT DO NOTHING path for real, not just defensively."""
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite_code = r.json()["invite_code"]

    await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()

    r = await bob.post(f"/rooms/{room_id}/leave", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text
    state = r.json()

    r = await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/join")
    assert r.status_code == 200, r.text

    assert await _participant_ids(room_id) == {bob.user_id}


async def test_game_started_and_ended_update_room_status(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")

    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]
    invite_code = r.json()["invite_code"]

    await bob.get(f"/rooms/by-code/{invite_code}")
    r = await bob.post(f"/rooms/{room_id}/join")
    state = r.json()

    r = await alice.post(
        f"/rooms/{room_id}/start", json={"expected_seq": state["seq"], "rules": {}}
    )
    assert r.status_code == 200, r.text
    state = r.json()

    row = await _room_row(room_id)
    assert row.status == "in_progress"
    assert row.ended_at is None

    r = await alice.post(f"/rooms/{room_id}/end", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    row = await _room_row(room_id)
    assert row.status == "ended"
    assert row.ended_at is not None


async def test_disband_sets_room_status_disbanded(make_device):
    alice = await make_device("Alice")

    r = await alice.post("/rooms")
    room_id = r.json()["room_id"]

    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    r = await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": state["seq"]})
    assert r.status_code == 200, r.text

    row = await _room_row(room_id)
    assert row.status == "disbanded"
    assert row.ended_at is not None
