# Taidi API

FastAPI backend wrapping `taidi_core` — the only write path to a room's
event log. See [docs/adr/0001-event-sourced-multiplayer-rooms.md](../docs/adr/0001-event-sourced-multiplayer-rooms.md)
for the design this implements.

## Run locally

```bash
# from the repo root
docker compose up -d postgres          # Postgres on localhost:5433, isolated project "taidi"
python3 -m venv .venv && source .venv/bin/activate   # once; `source` again each new session
pip install -r requirements-dev.txt    # installs gambrole-core and gambrole-api editable

cd api
alembic upgrade head                   # create the schema
uvicorn app.main:app --reload
```

The API is now at `http://localhost:8000` (`/docs` for interactive OpenAPI).

No external account is needed for local development — `TAIDI_AUTH_MODE=dev`
(the default) lets `POST /auth/dev-login {"display_name": "Alice"}` mint a
token for any name, which is what the frontend and the test suite both use
to simulate several players' devices at once.

## Test

```bash
pytest api/tests -q                              # integration tests against real Postgres
mypy --config-file api/pyproject.toml api/app     # strict
```

Tests create and wipe a separate `taidi_test` database automatically —
your dev data in `taidi` is untouched.

## Migrations

```bash
cd api
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

The database URL always comes from `TAIDI_DATABASE_URL` (via `app.config.settings`),
never from `alembic.ini` — dev, test, and production all migrate the same way
the app connects.

## How a request becomes an event

Every mutating endpoint (`/rooms/{id}/win`, `/cards`, `/special`, ...) does
the same thing:

1. Rebuild the room's current `RoomState` by folding its event log
   (`events_store.rebuild_state`) — there's no cached/denormalized state to
   go stale.
2. Hand the command to the matching `taidi_core.machine` function, which
   validates it against that state and returns the event(s) it produces
   (or raises `SeqConflict` / `NotAuthorized` / `IllegalTransition`, mapped
   to 409 / 403 / 400).
3. Insert those events. `UNIQUE(room_id, seq)` catches the rare case where
   two requests raced past step 1 with the same starting state — the loser's
   insert fails, and the endpoint retries once against the now-current state.
4. Return the freshly folded state as JSON.

## Structure

| Module | Purpose |
| --- | --- |
| `app/config.py` | Settings from environment (`TAIDI_*`) |
| `app/db.py` | Schema (`rooms`, `events`) and session management |
| `app/auth.py` | JWT verification; dev-mode token minting |
| `app/events_store.py` | Persistence + the fold back into `RoomState` |
| `app/schemas.py` | Request bodies for the command endpoints |
| `app/routers/rooms.py` | The room endpoints |
| `app/routers/auth.py` | `POST /auth/dev-login` |
| `alembic/` | Migrations |
