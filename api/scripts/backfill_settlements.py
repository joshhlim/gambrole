#!/usr/bin/env python3
"""One-off backfill for the settlements table added by migration
22b8206bab6a.

Every room that ended before this feature shipped has no `settlements`
rows, since nothing computed them before now. `/debts/me` and `/history/me`
will silently show no debts for those rooms until this has run once against
the target database.

Idempotent: rooms that already have settlement rows are skipped, and the
`settlements` table's UNIQUE(room_id, from_player, to_player) constraint
(enforced here via ON CONFLICT DO NOTHING) makes a second run a no-op even
if the per-room check somehow raced.

Usage (from `api/`, venv active, `TAIDI_DATABASE_URL` pointing at the
target database):
    python scripts/backfill_settlements.py [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "api"))

from app.db import async_session_factory  # noqa: E402
from app.db import rooms as rooms_table  # noqa: E402
from app.db import settlements as settlements_table  # noqa: E402
from app.events_store import rebuild_state_with_invite  # noqa: E402
from app.money import MAHJONG_CHIP_VALUE_CENTS  # noqa: E402
from mahjong_core.models import RoomState as MahjongRoomState  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from taidi_core.settlement import minimize_transfers  # noqa: E402


async def backfill(*, dry_run: bool) -> None:
    async with async_session_factory() as session:
        room_rows = (
            await session.execute(
                select(rooms_table.c.room_id, rooms_table.c.game_type).where(
                    rooms_table.c.status == "ended"
                )
            )
        ).all()
        print(f"Found {len(room_rows)} ended room(s).")

        for room_id, game_type in room_rows:
            existing = (
                await session.execute(
                    select(settlements_table.c.id).where(settlements_table.c.room_id == room_id)
                )
            ).first()
            if existing:
                continue  # already backfilled (or created live) — idempotent skip

            try:
                state, _invite_code, _game_type = await rebuild_state_with_invite(session, room_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  {room_id}: WARNING failed to replay ({exc!r}) — skipped")
                continue

            rate = MAHJONG_CHIP_VALUE_CENTS if isinstance(state, MahjongRoomState) else 1
            raw_settlements = minimize_transfers(state.balances)
            if not raw_settlements:
                continue

            if dry_run:
                print(f"  {room_id}: would insert {len(raw_settlements)} settlement(s)")
                continue

            await session.execute(
                pg_insert(settlements_table)
                .values(
                    [
                        {
                            "id": uuid4(),
                            "room_id": room_id,
                            "game_type": game_type,
                            "from_player": s.from_player,
                            "to_player": s.to_player,
                            "amount_cents": s.amount_cents * rate,
                            "status": "pending",
                            "created_at": state.ended_at,
                            "updated_at": state.ended_at,
                        }
                        for s in raw_settlements
                    ]
                )
                .on_conflict_do_nothing(index_elements=["room_id", "from_player", "to_player"])
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
