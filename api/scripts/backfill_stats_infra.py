#!/usr/bin/env python3
"""One-off backfill for the stats read-model added by migration
1fb1b0376169 (`rooms.status`/`.ended_at`, `room_participants`) — see
ADR-0007.

Every room created before that migration shipped has `status='lobby'`
(the column's server_default) regardless of its real state, and zero
`room_participants` rows for its non-host joiners, since nothing populated
either before now. `/stats/me` will silently show sparse/empty data for
pre-existing rooms until this has run once against the target database.

Usage (from `api/`, venv active, `TAIDI_DATABASE_URL` pointing at the
target database):
    python scripts/backfill_stats_infra.py [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "api"))

from app.db import async_session_factory  # noqa: E402
from app.db import events as events_table  # noqa: E402
from app.db import room_participants as room_participants_table  # noqa: E402
from app.db import rooms as rooms_table  # noqa: E402
from app.events_store import rebuild_state_with_invite  # noqa: E402
from sqlalchemy import select, update  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402


async def backfill(*, dry_run: bool) -> None:
    async with async_session_factory() as session:
        room_ids = [
            row.room_id for row in (await session.execute(select(rooms_table.c.room_id))).all()
        ]
        print(f"Found {len(room_ids)} room(s).")

        for room_id in room_ids:
            # Read raw player_joined events directly rather than a folded
            # state's .members, so a player who later left the lobby still
            # counts as a historical participant (leave_room deletes them
            # from .members, but they still played out that room's
            # history up to the point they left).
            join_rows = (
                await session.execute(
                    select(events_table.c.payload, events_table.c.created_at)
                    .where(events_table.c.room_id == room_id)
                    .where(events_table.c.type == "player_joined")
                )
            ).all()
            joins = [
                {
                    "room_id": room_id,
                    "player_id": UUID(row.payload["player_id"]),
                    "joined_at": row.created_at,
                }
                for row in join_rows
            ]

            # Defensive: a room whose events don't replay cleanly against
            # the *current* core package (e.g. old data from a schema that
            # has since changed underneath it) shouldn't take down the
            # whole backfill — skip its status/ended_at update but still
            # backfill what we can (its participants, read from raw events
            # rather than requiring a successful replay).
            try:
                state, _invite_code, _game_type = await rebuild_state_with_invite(session, room_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  {room_id}: WARNING failed to replay ({exc!r}) — participants only")
                state = None

            if dry_run:
                status = state.status.value if state else "REPLAY FAILED"
                print(f"  {room_id}: {len(joins)} participant(s), status={status}")
                continue

            if joins:
                await session.execute(
                    pg_insert(room_participants_table)
                    .values(joins)
                    .on_conflict_do_nothing(index_elements=["room_id", "player_id"])
                )
            if state is None:
                continue
            await session.execute(
                update(rooms_table)
                .where(rooms_table.c.room_id == room_id)
                .values(status=state.status.value, ended_at=state.ended_at)
            )

        if dry_run:
            print("Dry run — no changes committed.")
        else:
            await session.commit()
            print("Backfill committed.")


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    asyncio.run(backfill(dry_run=dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
