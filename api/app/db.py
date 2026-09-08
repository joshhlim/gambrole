"""Schema and session management.

Three tables:
- `rooms` holds the one piece of state that isn't derivable from the event
  log — the seed a room is created with (host, invite code, created_at).
  `RoomState.new(...)` is built directly from this row. `status`/`ended_at`
  are a denormalized projection of the event log (kept in sync by
  `events_store.append_events()` on game_started/game_ended/room_disbanded)
  so stats queries can filter to ended rooms in SQL instead of rebuilding
  every candidate room just to check — see ADR-0007.
- `events` is the append-only log. Every other field of RoomState (members,
  rules, rounds, balances, ...) is derived by folding events on top of the
  seed via `taidi_core.machine.fold`.
- `room_participants` is a materialized index of "who has ever joined this
  room" (excluding the host, who never emits a player_joined event — see
  ADR-0007), kept in sync by the same `append_events()` hook. Lets stats
  queries answer "which rooms has player X played in" without scanning
  every room's event log.

UNIQUE(room_id, seq) on `events` is the concurrency guard: two requests that
both compute the "next" seq can both try to insert it, but only one INSERT
succeeds — the loser gets an IntegrityError, mapped to HTTP 409 upstream.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

metadata = MetaData()

rooms = Table(
    "rooms",
    metadata,
    Column("room_id", PGUUID(as_uuid=True), primary_key=True),
    Column("invite_code", String(12), unique=True, nullable=False),
    Column("host_id", PGUUID(as_uuid=True), nullable=False),
    Column("host_display_name", String(100), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Which core package's machine/EventType a room's events fold through —
    # "taidi" (taidi_core) or "mahjong" (mahjong_core). See ADR-0006.
    Column("game_type", String(16), nullable=False, server_default="taidi"),
    # Denormalized from RoomState.status/.ended_at — see module docstring.
    Column("status", String(16), nullable=False, server_default="lobby"),
    Column("ended_at", DateTime(timezone=True), nullable=True),
    Index("ix_rooms_host_id", "host_id"),
)

events = Table(
    "events",
    metadata,
    Column("id", PGUUID(as_uuid=True), primary_key=True),
    Column("room_id", PGUUID(as_uuid=True), ForeignKey("rooms.room_id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("type", String(32), nullable=False),
    Column("actor", PGUUID(as_uuid=True), nullable=True),
    Column("payload", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("room_id", "seq", name="uq_events_room_seq"),
)

room_participants = Table(
    "room_participants",
    metadata,
    Column("room_id", PGUUID(as_uuid=True), ForeignKey("rooms.room_id"), nullable=False),
    Column("player_id", PGUUID(as_uuid=True), nullable=False),
    Column("joined_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("room_id", "player_id"),
    Index("ix_room_participants_player_id", "player_id"),
)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # Disables asyncpg's server-side prepared-statement cache. Harmless
    # locally; required once TAIDI_DATABASE_URL points at a connection
    # pooler in transaction mode (e.g. Supabase's pgbouncer) — prepared
    # statements don't survive being handed to a different physical
    # connection between statements under that mode, and asyncpg errors
    # with "prepared statement already exists" without this.
    connect_args={"statement_cache_size": 0},
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def init_models() -> None:
    """Create tables if they don't exist. Convenience for local dev/tests —
    the real migration path is Alembic (see api/alembic/)."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
