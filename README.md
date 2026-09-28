# GamBROle

Score keeping & settlements for Big Two (Taidi) and Mahjong nights.
Configurable house rules, multiplayer rooms where everyone plays from their
own phone, lifetime analytics. Live at
[gambrole.vercel.app](https://gambrole.vercel.app).

Two apps live in this repo: the **room app** (`core/` + `api/` + `web/`,
deployed on Vercel + Render + Supabase) and the older **legacy Streamlit
app** (`taidi.py`, deployed separately on Streamlit Community Cloud). The
first sections below are the legacy app's.

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
pip install -r requirements-dev.txt   # gambrole-core + gambrole-api editable, pinned tools
pytest tests -q       # legacy app: engine, persistence, end-to-end AppTest suites
pytest core/tests -q  # taidi_core + mahjong_core: scoring engines + room state machines
ruff check . && ruff format --check .
mypy --config-file core/pyproject.toml core/taidi_core
```

CI runs the same checks on every push and pull request (in a fresh runner,
which is its own isolation — no venv needed there), plus the API suite, a
migration round-trip with `alembic check` (models vs. migrations drift),
and the Playwright e2e suite. Render only deploys a commit once CI on it is
green.

**Pinned dependencies.** `api/requirements.lock` pins every third-party
package the API and core need; Render's build and `requirements-dev.txt`
both install from it, so CI tests exactly what gets deployed. After changing
dependencies in `api/pyproject.toml` or `core/pyproject.toml` (or merging a
Dependabot bump there), regenerate it with
`scripts/lock_api_deps.sh` (keeps existing pins; add `--upgrade` or
`--upgrade-package <name>` to bump) and commit the result. The dev tools
(ruff, mypy, pytest) are pinned directly in `requirements-dev.txt`.

### Optional passcode

Set `APP_PASSCODE = "..."` in secrets to require a shared passcode before the
app opens. Repeated wrong guesses lock the form out with a growing delay.
Leave it unset for no gate — but then restoring a backup, deleting finished
games, and the Danger zone are hidden, since anyone with the URL could use
them.

### Backups

Settings → Games → Backup downloads a JSON export of everything; the same
panel restores one (replacing all current data; needs `APP_PASSCODE`).

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

The `core/`/`api/`/`web/` stack (see ADR-0005) is live at
[gambrole.vercel.app](https://gambrole.vercel.app), with the API at
`https://gambrole-api-sg.onrender.com`. These are the steps it was set up
with, for rebuilding it from scratch. All three are free tiers; the API
sleeps on idle the same way the Streamlit app does. Do these in order —
later steps need values from earlier ones.

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
- Email auth is on by default. Sign-in is email + password (ADR-0008);
  under **Authentication → Sign In / Providers → Email**, turn off
  **Confirm email** so sign-up doesn't wait on an email — Supabase's
  built-in sender only allows a few messages an hour.

**2. API on Render** — [render.com](https://render.com) → New → Blueprint →
connect this repo. Render finds `render.yaml` automatically. After the first
deploy, fill in the env vars it left blank (Render dashboard → the service →
Environment):
- `TAIDI_DATABASE_URL` — the Supabase connection string from step 1.
- **If your project showed a JWT Signing Key** (no plain secret):
  `TAIDI_SUPABASE_URL` — the Project URL from step 1.
- **If your project showed a JWT Secret / Legacy JWT Secret**:
  `TAIDI_SUPABASE_JWT_SECRET` — that value instead.
- `TAIDI_CORS_ORIGINS` — leave blank for now (the API then only allows
  localhost origins); step 4 sets it once the Vercel URL exists.

`TAIDI_AUTH_MODE=supabase` is already set by the Blueprint; the API refuses
to start without an explicit auth mode.

Copy the Render URL it gives you (`https://gambrole-api-sg.onrender.com` or
similar) — step 3 needs it. `/healthz` is Render's (shallow) health check;
`/readyz` also runs `SELECT 1` against the database and returns 503 if it
can't reach it. The Blueprint pins the service to Render's
`singapore` region, next to the Supabase project (`ap-southeast-1`); every
request makes several database round trips, so keep the two in the same
region. Its first deploy fails until the `sync: false` variables above are
filled in — the build runs `alembic upgrade head`, which needs
`TAIDI_DATABASE_URL`. Fill them in and redeploy.

The Blueprint also pins `PYTHON_VERSION` (the same patch release CI uses),
redeploys on changes under `api/` or `core/` (`buildFilter`), and waits for
CI to pass before deploying (`autoDeployTrigger: checksPass`). Migrations
run in the build command, so the new schema goes live before the new code
and stays live if the deploy fails: keep every migration additive
(expand/contract — drop or rename things only in a later deploy).

**Keeping it awake.** A free Render service sleeps after 15 idle minutes
and takes ~30s to wake, and a free Supabase project pauses after a week
idle. `.github/workflows/keep-warm.yml` pings `/readyz` on a schedule, but
GitHub delivers scheduled runs too unreliably for that to work on its own —
set up a free [cron-job.org](https://cron-job.org) or UptimeRobot monitor
hitting `https://gambrole-api-sg.onrender.com/readyz` every 5-10 minutes
during game-night hours (15:00-03:00 SGT).

**3. Web on Vercel** — [vercel.com](https://vercel.com) → New Project →
import this repo → set **Root Directory** to `web`. Add these environment
variables before deploying:

Don't mark any of these **Sensitive** — Vercel won't save a Sensitive
variable with a `NEXT_PUBLIC_` name, and none of them are secret (the
browser needs every one). They're baked in at build time, so changing one
later needs a redeploy.

```
NEXT_PUBLIC_API_URL=<the Render URL from step 2>
NEXT_PUBLIC_AUTH_MODE=supabase
NEXT_PUBLIC_SUPABASE_URL=<Project URL from step 1>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key from step 1>
```

**4. Loop back** — in Supabase, Authentication → URL Configuration, add the
Vercel URL to **Redirect URLs** (`https://your-app.vercel.app/auth/callback`)
so password-reset and email-change links land back in the app. In Render, update `TAIDI_CORS_ORIGINS`
to `["https://your-app.vercel.app"]` and redeploy.

Open the Vercel URL, sign up with an email and password, and you're on the
real stack. `web/README.md` and `api/README.md` have the day-to-day dev commands;
ADR-0005 has the reasoning behind these choices.

## Backups (room app)

`.github/workflows/backup.yml` runs weekly (and on demand from the Actions
tab) and `pg_dump`s the app's tables (the `public` schema — Supabase keeps
the accounts themselves) into an **encrypted** artifact kept for 30 days.
The repo is public and so are its Actions artifacts, which is why the dump
is encrypted before upload. It does nothing until two repository secrets
exist (Settings → Secrets and variables → Actions):

- `BACKUP_DATABASE_URL` — the Supabase **Session pooler** connection string
  as a plain `postgresql://...` URL (not `+asyncpg`; the direct connection
  is IPv6-only and GitHub's runners can't reach it).
- `BACKUP_PASSPHRASE` — a long random passphrase. Keep a copy somewhere
  other than GitHub.

To restore, download the artifact from the run's page, then:

```bash
unzip gambrole-db-<stamp>.zip
gpg --decrypt --batch --passphrase "$BACKUP_PASSPHRASE" \
    --output gambrole.dump gambrole-<stamp>.dump.gpg
pg_restore --list gambrole.dump               # inspect first
pg_restore --clean --if-exists --no-owner --no-privileges \
    --dbname "postgresql://..." gambrole.dump   # replaces the app's tables
```

Try it against the local database (`docker compose up -d postgres`,
`postgresql://gambrole:gambrole_dev@localhost:5433/gambrole`) before
pointing it at production. `pg_restore` must be version 17 or newer.

## Roadmap

The app is evolving from a single-scorekeeper tool into a multiplayer room
where every player acts from their own phone. See `docs/adr/` for the design
decisions (event-sourced rooms, the pure-Python core, the API's single write
path, the frontend, and account/deployment choices), `CHANGELOG.md` for
progress, and **`PROGRESS.md`** for a living session-handoff snapshot — read
that first when picking this project back up.

`core/` (`taidi_core`, `mahjong_core`) holds the domain packages
implementing that design, `api/` is a FastAPI backend built on them, and
`web/` is the Next.js PWA frontend — together they're the room app live at
gambrole.vercel.app. The legacy Streamlit app (`db.py`/`ui.py` below) is
still deployed separately. The full slice runs locally:
`docker compose up -d postgres`, then see [api/README.md](api/README.md)
and [web/README.md](web/README.md). The Playwright suites in `web/e2e/`
(`full-game.spec.ts` drives three browser contexts through a full game)
are the end-to-end proof:

```bash
docker compose up -d postgres
source .venv/bin/activate
(cd api && python -m alembic upgrade head)
cd web && TAIDI_AUTH_MODE=dev npx playwright test   # starts the API and web app itself
```

## Structure

### Legacy app (Streamlit)

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
| `app/db.py` | Schema (`rooms`, `events`, read-model tables) and session management |
| `app/auth.py` | Pluggable JWT auth: dev-mode token minting or Supabase verification |
| `app/events_store.py` | Persistence + folding the event log back into a `RoomState` |
| `app/routers/rooms.py` | The room command endpoints |
| `alembic/` | Migrations (additive only — see Deploy) |
| `requirements.lock` | Exact dependency pins Render and CI install |

### `web/` — Next.js PWA frontend

See [web/README.md](web/README.md) and ADR-0004.

| Path | Purpose |
| --- | --- |
| `src/app/page.tsx` | Home: sign-in, new room, join by code |
| `src/app/room/[roomId]/page.tsx` | Lobby, live table, ended-game views |
| `src/lib/api.ts` | Typed fetch client; auto-retries a command once on 409 |
| `src/lib/usePolling.ts` | Stands in for Supabase Realtime for now |
| `e2e/full-game.spec.ts` | Three-device end-to-end proof |
