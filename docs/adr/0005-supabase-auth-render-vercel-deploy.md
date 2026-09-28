# ADR-0005: Real accounts via Supabase Auth; Render + Vercel for hosting

- Status: accepted; decision 1, the magic-link part of decision 4, and the
  `dev` default in decision 3 superseded by ADR-0008
- Date: 2026-09-01

## Context

Everything through Phase 2 (ADR-0001 through ADR-0004) ran entirely on
`TAIDI_AUTH_MODE=dev` — the API's own token minter, no external identity
provider. That was always meant as a stand-in (see ADR-0003) until Phase 3's
account-dependent work (lifetime stats, rulesets tied to a person, claiming a
guest player) needed something a person can actually return to across
sessions. Before building any of that, the app needs real accounts and a
place to run that isn't a laptop.

## Decision

1. *(Superseded by ADR-0008: email + password replaced magic links.)*
   **Magic-link email auth only, not Google OAuth yet.** Supabase supports
   email links with zero extra setup; Google sign-in would need a separate
   Google Cloud Console project and OAuth consent screen — a second external
   account-creation flow this phase doesn't need to force. `auth.ts`'s mode
   switch makes adding a Google button later additive, not a rewrite.
2. **The API deploys to Render, not Vercel serverless.** The app holds a
   persistent async connection pool (SQLAlchemy + asyncpg) and expects to
   stay warm between requests within a process — exactly what a serverless
   function's cold-start/short-lived-invocation model fights. Render runs
   the existing `uvicorn app.main:app` unchanged, free tier, same idle-sleep
   tradeoff already familiar from the Streamlit deploy. Vercel remains the
   right host for the Next.js frontend — that's what it's built for.
3. **Auth mode is a pure config switch on both sides**, not a code fork.
   `TAIDI_AUTH_MODE`/`NEXT_PUBLIC_AUTH_MODE` default to `dev` everywhere
   they're not explicitly set to `supabase` — local development and CI never
   touch Supabase and keep working exactly as before. `lib/auth.ts` exposes
   the same `getStoredAuth`/`useStoredUser`/`CurrentUser` surface regardless
   of which mode is active; `api.ts` and every page that reads the current
   user needed zero changes.
4. **The display name rides inside the JWT via `user_metadata`,** set at
   magic-link request time (`signInWithOtp({ options: { data: {
   display_name } } })`). The API's `_display_name_from_claims` already
   looked there first (written speculatively in ADR-0003, before a real
   Supabase project existed to confirm against) — this phase is what proved
   that assumption correct, with a hand-crafted-token test
   (`test_auth_supabase_mode.py`) standing in for the real thing until a
   project exists.
5. **`statement_cache_size: 0`** on the asyncpg engine (`db.py`), added
   defensively regardless of which connection string ends up used. Supabase's
   pooled connection string (pgbouncer, transaction mode) doesn't survive
   asyncpg's server-side prepared-statement cache — a statement prepared on
   one physical connection can get handed to a different one mid-session and
   fail with "prepared statement already exists." Costs nothing on a direct
   connection; required the moment anyone points `TAIDI_DATABASE_URL` at a
   pooler.

## Consequences

- Everything in this phase was verifiable *before* a Supabase/Render/Vercel
  account exists: the JWT verification logic against a hand-built token
  matching Supabase's real claim shape, the Render build command against a
  clean venv (not the developer's already-populated one), and the frontend's
  mode-branching by toggling env vars against a fake project URL. The actual
  external account creation is a short, mechanical handoff — see the root
  README's "Deploy" section.
- Rulesets and other account-scoped features can now be built against a
  `user_id` that's stable across sessions instead of a fresh random UUID
  minted on every dev-login — the blocker Phase 3 stats and rulesets were
  waiting on.
- Not yet done: RLS policies, Sentry, scheduled backups, and the guest-player
  claim flow — those stay queued behind this phase's actual deploy, since
  several of them need to be tested against the real hosted database, not a
  local one.

## Update (same day, during the actual account creation)

The real Supabase project turned out to use a **JWT Signing Key**
(asymmetric, verified via a public JWKS endpoint), not the shared HS256
secret this ADR's decision 4 assumed — Supabase has moved newer projects to
that model by default. `auth.py` now supports both: JWKS (`TAIDI_SUPABASE_URL`,
via `PyJWKClient`) is tried first when configured, falling back to the shared
secret (`TAIDI_SUPABASE_JWT_SECRET`) for older projects that still have one.
`pyjwt[crypto]` (pulls in `cryptography`) was added to `api/`'s dependencies
— asymmetric algorithms don't work without it, caught before it could fail
silently in production by the same clean-venv verification approach as the
Render build command. Both paths are covered in
`test_auth_supabase_mode.py`, the JWKS one using a real generated EC keypair
and a monkeypatched `PyJWKClient.fetch_data` rather than a live network call.
No other part of the design changed.
