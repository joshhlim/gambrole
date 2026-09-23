#!/usr/bin/env python3
"""Seed the `users` directory from Supabase's own auth.users, so friend
search works for everyone from day one instead of only for people who have
opened the app since the feature shipped.

This is the one place the app looks at Supabase's auth schema. It's a
one-off: after this, rows are kept fresh from JWT claims (users_service.
ensure_user). Local dev and the test suite have no auth schema at all, which
is exactly why the app doesn't read it at request time.

Anyone the app knows from room history but who has no auth.users row (dev
accounts, deleted users) is seeded from the display name recorded in the
room they hosted or joined, so friend lists never show a blank.

Usage (from `api/`, venv active, TAIDI_DATABASE_URL pointing at the target):
    python scripts/backfill_users.py [--dry-run]
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
from app.db import rooms as rooms_table  # noqa: E402
from app.db import users as users_table  # noqa: E402
from app.time import utcnow  # noqa: E402
from app.users_service import assign_username, suggest_username  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402


async def _auth_users(session) -> list[dict]:
    """Supabase's account records, or an empty list where there's no auth
    schema (local dev / tests)."""
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, email, raw_user_meta_data->>'display_name' AS display_name "
                    "FROM auth.users"
                )
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        print(f"  no readable auth.users ({type(exc).__name__}) — room history only")
        await session.rollback()
        return []
    return [
        {
            "user_id": r.id,
            "email": (r.email or "").strip().lower() or None,
            "display_name": (r.display_name or r.email or "Player").strip(),
        }
        for r in rows
    ]


async def _from_room_history(session) -> dict:
    """player_id -> display name, for anyone the app has seen play."""
    known: dict = {}
    for row in (
        await session.execute(select(rooms_table.c.host_id, rooms_table.c.host_display_name))
    ).all():
        known[row.host_id] = row.host_display_name
    joins = (
        await session.execute(
            select(events_table.c.payload).where(events_table.c.type == "player_joined")
        )
    ).all()
    for row in joins:
        payload = row.payload or {}
        pid, name = payload.get("player_id"), payload.get("display_name")
        if pid and name:
            known[UUID(pid)] = name
    return known


async def backfill(*, dry_run: bool) -> None:
    async with async_session_factory() as session:
        accounts = await _auth_users(session)
        print(f"Found {len(accounts)} auth account(s).")

        seeded = {a["user_id"] for a in accounts}
        history = await _from_room_history(session)
        extra = [
            {"user_id": pid, "email": None, "display_name": name}
            for pid, name in history.items()
            if pid not in seeded
        ]
        print(f"Found {len(extra)} additional player(s) from room history.")

        now = utcnow()
        rows = [{**a, "created_at": now, "updated_at": now} for a in [*accounts, *extra]]
        if not rows:
            print("Nothing to seed.")
            return

        if dry_run:
            for r in rows:
                shown = r["email"] or "(no email)"
                print(f"  {str(r['user_id'])[:8]}  {r['display_name']:<20} {shown}")
            print("Dry run — no changes committed.")
            return

        # Re-runnable: refresh the name/email, never clobber a claimed
        # username, and never resurrect an email as NULL.
        stmt = pg_insert(users_table).values(rows)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "display_name": stmt.excluded.display_name,
                    "email": func.coalesce(stmt.excluded.email, users_table.c.email),
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
        await session.commit()
        print(f"Seeded {len(rows)} user(s).")

        # Everyone needs a handle: friends search by it, and the app should
        # never show a player without one. Derived from their address, and
        # changeable in Settings afterwards.
        missing = (
            await session.execute(
                select(
                    users_table.c.user_id, users_table.c.email, users_table.c.display_name
                ).where(users_table.c.username.is_(None))
            )
        ).all()
        for row in missing:
            handle = await assign_username(
                session, row.user_id, suggest_username(row.email, row.display_name)
            )
            print(f"  @{handle:<20} {row.display_name}")
        print(f"Assigned {len(missing)} username(s).")


def main() -> int:
    asyncio.run(backfill(dry_run="--dry-run" in sys.argv[1:]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
