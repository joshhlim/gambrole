# ADR-0007: A stats read-model — persisted room status + a participants index

- Status: accepted
- Date: 2026-09-08

## Context

Building an analytics dashboard (`GET /stats/me`) needs to answer two
questions cheaply for any signed-in player: "which rooms has this player
ever played in?" and "which of those are actually finished (so their
numbers are final)?"

Neither is answerable today without expensive work. There's no users
table — identity is JWT-only (`CurrentUser(user_id, display_name)`, no
server-side user row) — so there's nowhere to store "player X's rooms" as
a foreign key relationship. The `rooms` table has `host_id` but no
membership list; `RoomState.members` only exists as *folded* state,
rebuilt by replaying a room's full event log. And `rooms` has no `status`
or `ended_at` columns either — `RoomState.status`/`.ended_at` are also
fold-only. Answering either question naively means rebuilding every room
in the database just to check whether the current user was in it and
whether it's finished — fine for one room, unworkable for a dashboard that
needs to do this across every room a player has ever touched.

## Decision

Add two pieces of denormalized read-model, both kept in sync inside
`events_store.append_events()` — the single choke point every write to the
event log already passes through (both `routers/rooms.py` and
`routers/mahjong.py` call it, and nothing else touches the `events` table):

1. **`room_participants(room_id, player_id, joined_at)`**, a row inserted
   whenever a `PLAYER_JOINED` event is persisted. The **host is
   deliberately excluded**: `create_room` builds `RoomState.new()` directly
   and never emits a `PLAYER_JOINED` event for the host, so a query for
   "rooms player X has history in" always unions `room_participants` with
   `rooms.host_id = X`. The table is append-only by design — a player who
   later leaves a lobby (`PLAYER_LEFT`) keeps their row, since it records
   "was here at some point," not current membership; this is harmless
   because leaving is lobby-only, so a departed player never appears in an
   *ended* room's final state either way.

2. **`rooms.status`/`rooms.ended_at`**, kept in sync with `RoomState.status`
   on `GAME_STARTED` → `in_progress`, `GAME_ENDED` → `ended`, and
   `ROOM_DISBANDED` → `disbanded` (both event-type checks are plain string
   comparisons, not enum-membership checks — `taidi_core.EventType` and
   `mahjong_core.EventType` share these exact string values, so the hook
   stays game-type-agnostic and works for either game's events without
   knowing which one it's looking at).

The event log remains the single source of truth for both. These columns
are a projection of it, not new authoritative state — if they were ever
lost or found to have drifted, they're fully re-derivable by replaying the
event log (see the backfill script below, which does exactly that).

A one-off script, `api/scripts/backfill_stats_infra.py`, populates both for
every room that existed before this migration shipped (otherwise
pre-existing games would silently show up as empty in the dashboard). It
reads `player_joined` events directly from the raw log rather than a
folded state's `.members` (so a player who later left still counts), and
defensively skips the `status`/`ended_at` update — while still backfilling
what it can of that room's participants — for any room whose event log
fails to replay against the *current* core package (observed in practice
against very old local dev data predating the Mahjong chips/tai-table
rework), so one bad room can't abort the whole backfill.

## Consequences

- Every `player_joined`/`game_started`/`game_ended`/`room_disbanded` event
  now does one or two extra cheap writes. Negligible at this app's write
  volume (these events happen a handful of times per game, not per action).
- `GET /stats/me` can find a player's ended rooms with a plain SQL filter
  (`UNION` of two indexed lookups) instead of rebuilding every room in the
  database to check status and membership — the entire reason this ADR
  exists.
- The projection can in principle drift from the event log if a future
  write path ever bypasses `events_store.append_events()`. Mitigated by
  there being exactly one write path today, and by the projection being
  cheaply re-derivable via the backfill script if drift is ever suspected.
- `MAHJONG_CHIP_VALUE_CENTS = 50` (1 chip = $0.50), used to fold Mahjong's
  chip-denominated balances into the dashboard's combined dollar figures,
  lives in `api/app/stats_service.py` — not in `mahjong_core`, which stays
  currency-agnostic domain logic, and not in `mahjong_core.stats`, which
  stays chip-denominated. This is a display-layer concern, not a schema
  decision, so it doesn't warrant its own ADR — noted here only because it
  lives alongside this read-model in the same feature.

## Alternatives considered

- **Rebuild every room a player has ever touched, on every stats request.**
  Rejected — this turns a cheap indexed SQL filter into an O(all rooms)
  fold on every dashboard load, and stops scaling even at this app's
  friend-group volume once a player has played a few hundred games.
- **A fully materialized per-player stats snapshot, refreshed on
  `game_ended`.** Deferred, not rejected outright — real added complexity
  (a snapshot table, invalidation logic) that isn't justified until
  rebuild-per-request against the participants index actually proves slow
  in practice. The current design already computes everything in one pass
  per request (see `stats_service.build_stats_for`), so this is a
  straightforward next step if it's ever needed, not a redesign.
