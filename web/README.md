# Taidi Web

Next.js PWA for Taidi — every player acts from their own device. See
[docs/adr/0004-nextjs-pwa-and-polling.md](../docs/adr/0004-nextjs-pwa-and-polling.md)
for the design.

## Run locally

```bash
# from the repo root: postgres + api must be running first
docker compose up -d postgres
source .venv/bin/activate   # see root README.md — shared venv for all Python packages
cd api && alembic upgrade head && uvicorn app.main:app --reload &
cd ../web
cp .env.local.example .env.local   # points at the local API by default
npm install
npm run dev -- --port 3100
```

Open `http://localhost:3100`. `TAIDI_AUTH_MODE=dev` on the API (the
default) means the sign-in screen mints a token for any name — no external
account needed, and different browser tabs/contexts with different names
act as different players, which is how the e2e tests simulate multiple
phones.

Port 3100 (not Next.js's default 3000) is just this repo's convention —
3000 is often already taken by something else on a shared dev machine.

## Test

```bash
source ../.venv/bin/activate   # playwright.config.ts launches the API itself
npm run lint
npm run build                # also typechecks — Next.js generates route
                              # types (e.g. LayoutProps) during build/dev,
                              # so a bare `tsc --noEmit` fails on a fresh
                              # checkout that hasn't built yet
npx playwright test          # drives 3 browser contexts through a full game
```

`playwright.config.ts` starts both the API (`:8000`) and the web app
(`:3100`) itself — no servers need to be running beforehand for
`playwright test` specifically (only for `npm run dev`).

## iOS app

The iOS app is this same site, built as static files (`output: "export"`)
and bundled into a native shell with [Capacitor](https://capacitorjs.com).
`ios/` is the Xcode project; the site copy inside it (`ios/App/App/public`)
is generated and not committed.

```bash
cp .env.app.example .env.app   # once — production API + Supabase values
npm run build:app              # next build with .env.app, then copy into ios/
npm run open:ios               # opens Xcode — pick a Simulator or your iPhone, press Run
```

Rerun `npm run build:app` after any web change; the app only sees what was
last copied in. The API must allow the app's origin: `capacitor://localhost`
in `TAIDI_CORS_ORIGINS`.

## Structure

| Path | Purpose |
| --- | --- |
| `src/app/page.tsx` | Home: dev sign-in, new room, join by code |
| `src/app/room/page.tsx` | Lobby, live table, and ended-game views (`/room?id=…`) |
| `src/app/manifest.ts` | PWA manifest |
| `src/lib/auth.ts` | Token storage; dev-mode sign-in |
| `src/lib/api.ts` | Typed fetch client for every room endpoint |
| `src/lib/usePolling.ts` | Stands in for Supabase Realtime for now |
| `src/lib/types.ts` | Hand-kept mirror of `taidi_core`'s JSON shape |
| `e2e/full-game.spec.ts` | Three-device end-to-end proof |
