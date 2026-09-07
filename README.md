# Taidi Tracker

Score keeping & settlements for Big Two (Taidi) nights. Configurable house
rules, autosaving games, lifetime analytics.

## Run locally

All Python packages in this repo (the Streamlit app, `taidi_core`, and the
FastAPI backend) share one virtualenv at the repo root — create it once:

```bash
python3 -m venv .venv
source .venv/bin/activate   # every session, before running anything Python
pip install -r requirements.txt
streamlit run taidi.py
```

Data is stored in a local `taidi.db` SQLite file.

### Develop

```bash
source .venv/bin/activate   # if not already active
pip install -r requirements-dev.txt   # installs taidi_core and taidi_api editable too
pytest tests -q       # legacy app: engine, persistence, end-to-end AppTest suites
pytest core/tests -q  # taidi_core: scoring engine + room state machine
ruff check . && ruff format --check .
mypy --config-file core/pyproject.toml core/taidi_core
```

CI runs the same checks on every push and pull request (in a fresh runner,
which is its own isolation — no venv needed there).

### Optional passcode

Set `APP_PASSCODE = "..."` in secrets to require a shared passcode before the
app opens. Leave it unset for no gate.

### Backups

Settings → Games → Backup downloads a JSON export of everything; the same
panel restores one (replacing all current data).

## Deploy (Streamlit Community Cloud + Turso)

1. Push this repo to GitHub.
2. Create a free database at [turso.tech](https://turso.tech); copy its URL and
   an auth token.
3. Create the app at [share.streamlit.io](https://share.streamlit.io) pointing
   at `taidi.py`, and add to the app secrets:

   ```toml
   TURSO_DATABASE_URL = "libsql://<db>-<org>.turso.io"
   TURSO_AUTH_TOKEN = "<token>"
   ```

When those secrets are present the app stores everything in Turso (survives
redeploys and restarts); without them it falls back to the local file.

## Deploy the room app (Supabase + Render + Vercel)

The `core/`/`api/`/`web/` stack (see ADR-0005) isn't live anywhere yet. All
three are free tiers; the API sleeps on idle the same way the Streamlit app
does. Do these in order — later steps need values from earlier ones.

**1. Supabase** — [supabase.com](https://supabase.com) → New Project. When
prompted, disable "Enable Data API" (this app never queries Supabase's
REST layer — the API talks to Postgres directly, and the frontend only ever
talks to the API); leave automatic RLS on. Once it's created:
- **Project Settings → API** → copy the **`publishable`** (or **`anon`
  `public`**) key — *not* `secret`/`service_role`, which this app never
  uses. The **Project URL** is usually here too; if not, check **Project
  Settings → General** for the **Reference ID** and build it as
  `https://<reference-id>.supabase.co`.
- Same page: look for a **JWT Secret** / **Legacy JWT Secret** you can
  reveal. Newer projects show a **JWT Signing Key** instead with no plain
  secret — that's fine, just note which case you're in for step 2.
- **Project Settings → Database → Connection string** → copy the **URI**.
  Prefix it with `postgresql+asyncpg://` in place of `postgresql://`
  (SQLAlchemy needs the driver named explicitly).
- Email auth is on by default — nothing to configure for magic links.

**2. API on Render** — [render.com](https://render.com) → New → Blueprint →
connect this repo. Render finds `render.yaml` automatically. After the first
deploy, fill in the env vars it left blank (Render dashboard → the service →
Environment):
- `TAIDI_DATABASE_URL` — the Supabase connection string from step 1.
- **If your project showed a JWT Signing Key** (no plain secret):
  `TAIDI_SUPABASE_URL` — the Project URL from step 1.
- **If your project showed a JWT Secret / Legacy JWT Secret**:
  `TAIDI_SUPABASE_JWT_SECRET` — that value instead.
- `TAIDI_CORS_ORIGINS` — leave as `["http://localhost:3000"]` for now;
  step 4 updates it once the Vercel URL exists.

Copy the Render URL it gives you (`https://gambrole-api.onrender.com` or
similar) — step 3 needs it.

**3. Web on Vercel** — [vercel.com](https://vercel.com) → New Project →
import this repo → set **Root Directory** to `web`. Add these environment
variables before deploying:

```
NEXT_PUBLIC_API_URL=<the Render URL from step 2>
NEXT_PUBLIC_AUTH_MODE=supabase
NEXT_PUBLIC_SUPABASE_URL=<Project URL from step 1>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key from step 1>
```

**4. Loop back** — in Supabase, Authentication → URL Configuration, add the
Vercel URL to **Redirect URLs** (`https://your-app.vercel.app/auth/callback`)
so magic links can complete sign-in. In Render, update `TAIDI_CORS_ORIGINS`
to `["https://your-app.vercel.app"]` and redeploy.

Open the Vercel URL, sign in with a real email, and you're on the real
stack. `web/README.md` and `api/README.md` have the day-to-day dev commands;
ADR-0005 has the reasoning behind these choices.

## Roadmap

The app is evolving from a single-scorekeeper tool into a multiplayer room
where every player acts from their own phone. See `docs/adr/` for the design
decisions (event-sourced rooms, the pure-Python core, the API's single write
path, the frontend, and account/deployment choices), `CHANGELOG.md` for
progress, and **`PROGRESS.md`** for a living session-handoff snapshot — read
that first when picking this project back up.

`core/taidi_core` is the new domain package implementing that design,
`api/` is a FastAPI backend built on it, and `web/` is the Next.js PWA
frontend — none of it is wired into the deployed app yet (see `db.py`/
`ui.py` below for what actually runs in production today). The full slice
runs locally: `docker compose up -d postgres`, then see
[api/README.md](api/README.md) and [web/README.md](web/README.md).
`web/e2e/full-game.spec.ts` drives three browser contexts through a full
game as the end-to-end proof.

## Structure

### Deployed app (Streamlit)

| File      | Purpose                                              |
| --------- | ---------------------------------------------------- |
| `taidi.py`| Entry point and page routing                         |
| `game.py` | Game rules, scoring engine, lifetime stats           |
| `db.py`   | Persistence (local SQLite or Turso)                  |
| `ui.py`   | All rendering: CSS, home screen, pages               |

### `core/` — `taidi_core`, the multiplayer domain package

A separate, installable package (own `pyproject.toml`, own tests) with no
Streamlit/pandas dependency — see ADR-0002.

| Module                     | Purpose                                                    |
| --------------------------- | ----------------------------------------------------------- |
| `taidi_core/models.py`      | Typed vocabulary: `GameRules`, `Transfer`, `RoundState`, `RoomState`, `Event`, `PlayerStats`, `Settlement` |
| `taidi_core/rules.py`       | The scoring engine (card transfers, special-hand transfers) |
| `taidi_core/machine.py`     | The room/round event-sourced state machine                  |
| `taidi_core/stats.py`       | Lifetime stats derived from ended rooms                     |
| `taidi_core/settlement.py`  | Pairwise netting and greedy debt minimization                |
| `scripts/migrate_legacy_to_events.py` | Migrates legacy Streamlit archives into `taidi_core` rooms, verifying balances match |

### `api/` — FastAPI backend

The only write path to a room — see [api/README.md](api/README.md) and
ADR-0003. `docker-compose.yml` at the repo root runs a local Postgres for it.

| Module | Purpose |
| --- | --- |
| `app/db.py` | Schema (`rooms`, `events`) and session management |
| `app/auth.py` | Pluggable JWT auth: dev-mode token minting or Supabase verification |
| `app/events_store.py` | Persistence + folding the event log back into a `RoomState` |
| `app/routers/rooms.py` | The room command endpoints |
| `alembic/` | Migrations |

### `web/` — Next.js PWA frontend

See [web/README.md](web/README.md) and ADR-0004.

| Path | Purpose |
| --- | --- |
| `src/app/page.tsx` | Home: sign-in, new room, join by code |
| `src/app/room/[roomId]/page.tsx` | Lobby, live table, ended-game views |
| `src/lib/api.ts` | Typed fetch client; auto-retries a command once on 409 |
| `src/lib/usePolling.ts` | Stands in for Supabase Realtime for now |
| `e2e/full-game.spec.ts` | Three-device end-to-end proof |
