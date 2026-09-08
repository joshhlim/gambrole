# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.6.1] - 2026-09-08

### Changed
- Finished the rename from "Taidi Tracker" to **GamBROle** at the project
  level: the GitHub repo, the local project directory, README/docs
  branding, the Python distribution package names (`taidi-core` →
  `gambrole-core`, `taidi-api` → `gambrole-api`, plus `web`'s package.json
  → `gambrole-web`), and the local dev Postgres naming
  (`docker-compose.yml`, CI's service container, test fixtures). The
  `taidi_core` Python package itself keeps its name — it's the Big Two/
  Taidi game engine specifically, the same way `mahjong_core` is named for
  Mahjong; GamBROle is the umbrella app containing both. Deployed infra
  (Render, Vercel, Supabase) and the `TAIDI_*` environment variable names
  are untouched by this change — those need a separate, manually-
  coordinated step since they can't be edited from the repo.

## [0.6.0] - 2026-09-08

**Analytics dashboard is live** — "My Stats" is no longer a placeholder.

### Added
- A main overview: combined total winnings and a cumulative trend chart
  across both games (Taidi's cents and Mahjong's chips, converted at a
  fixed 1 chip = $0.50), per-game subtotals, total/per-game session
  counts, a win/loss streak, favorite game, and last-played date.
- A Taidi tab: round win rate (rounds where you pressed "I win" / rounds
  played), profit rate, double rate and triple rate (of your *losing*
  rounds, since the multiplier only ever applies to a payer's own card
  count), special hands claimed, and best/worst round.
- A Mahjong tab: HU rate, a win-method breakdown (direct/zimo/bao), tai
  distribution and average, dealer win rate, a profit breakdown by action
  type (YAO/GANG/HU/BAO/bonuses), and best/worst hand.
- `GET /stats/me` — one combined endpoint computing all of the above in a
  single pass over every ended room a player has history in, backed by a
  new read-model (`rooms.status`/`.ended_at`, a `room_participants` index)
  that makes "which of my rooms are finished" a plain SQL filter instead
  of replaying every room in the database (ADR-0007).
- `TaidiPlayerStats`/`MahjongPlayerStats` round/hand-level aggregators in
  `core/`, layered on top of the existing room-level lifetime stats.
  Mahjong's `HandState` now also records each hand's win mode/tai/bonus
  flags, previously discarded after settlement.

## [0.5.6] - 2026-09-04

### Changed
- Mahjong table view: player cards are now a fixed size regardless of
  display name length (previously they sized to their own content and
  looked inconsistent), and slightly larger. Dropped the "Wind X · Dealer
  ... — name" caption line under the table now that the center badge and
  dealer highlighting cover that.

## [0.5.5] - 2026-09-04

### Changed
- The Mahjong table view is now a diamond around the table instead of a
  vertical list: you at the bottom, the next seat clockwise on your right,
  the previous seat on your left, and the seat across from you at the
  top. A circular badge in the center shows the current wind + dealer
  seat as a compact two-character glyph (e.g. 東東 for wind 1 dealer seat
  1, 西南 for wind 3 dealer seat 2). The dealer's card gets a gold
  border/background, and your own card is tagged "(you)" — both can
  appear on the same card at once without conflict.

## [0.5.4] - 2026-09-04

### Fixed
- Mahjong dealer/wind rotation was gang-driven for every hand close, which
  didn't match the intended rule. It's now: on a WIN, the dealer stays if
  the dealer themselves won and rotates otherwise (gang presence no longer
  matters for a win); on a NO WIN, the dealer stays unless a gang happened
  this hand, in which case it still rotates. The last seat of the last
  wind is unchanged — only a WIN closes that cycle.

## [0.5.3] - 2026-09-04

### Added
- A "5/1 半" Mahjong preset: base 500, yao 3, gang 3, zimo bonus 5, KLPPDD
  5, tai 1-7 paying hu 4/8/16/32/64/128/256 and zimo 2/4/8/16/32/64/128.

## [0.5.2] - 2026-09-04

Two optional Mahjong HU bonuses, on top of the tai payout: a zimo bonus and
KLPPDD.

### Added
- `MahjongRules.zimo_bonus_chips` (default 0): a flat extra amount each of
  the other 3 players pays a self-drawn (zimo) winner, toggled per-hand.
  Not available on a direct or bao win.
- `MahjongRules.klppdd_chips` (default 0): a flat extra amount toggled
  per-hand on any win. It mirrors whatever payer structure the win already
  uses — split 3 ways on a zimo win, paid in full (×3) by the single payer
  on a direct or bao win. Stacks independently with BAO and with the zimo
  bonus. `ENGINE_VERSION` bumped to `mahjong-3`.
- `declare_hu` takes new `zimo_bonus`/`klppdd` booleans; the `/hu` endpoint
  and `HuFlow` UI expose them as toggle buttons in the tai-selection step
  (zimo bonus only shown for a self-draw). The New Room Mahjong form gained
  matching optional rule inputs.

## [0.5.1] - 2026-09-04

Mahjong now scores in chips against a real stakes table instead of a
placeholder linear dollar rate.

### Changed
- `MahjongRules` money fields are now `base_chips`, `yao_chips`,
  `gang_chips`, and a `tai_table` (a per-tai-level `{hu, zimo}` lookup,
  since real mahjong payouts aren't linear in tai — a 5-tai hand pays far
  more than 5x a 1-tai hand). Replaces `yao_unit_cents`/`gang_unit_cents`/
  `tai_unit_cents`/`zimo_unit_cents`. `ENGINE_VERSION` bumped to
  `mahjong-2`.
- The default rules (and the New Room preset) are now a real table: "3/6
  半" — base 300, yao 2, gang 2, tai 1-5 paying hu 4/7/11/20/40 and zimo
  4/5/7/12/22.
- The New Room Mahjong form now edits the tai table directly (a row per
  tai level, add/remove rows as `max_tai` changes) instead of a single
  linear rate.
- The table UI displays each player's chip stack (`base_chips` + net),
  not a raw profit/loss number — reads like real chips in front of them.

## [0.5.0] - 2026-09-03

**Mahjong is live** — the second playable game (Phase E, the final slice of
the leave/disband + Mahjong plan). The "Coming soon" tile on New Room now
works end to end.

### Added
- Full Mahjong room UI: a lobby seat-arranger (host taps two players to
  swap their 東/南/西/北 seats before starting), a live table showing wind/
  dealer, running balances in turn order from the viewer's own seat, the
  three action buttons (咬 YAO / 槓 GANG / 胡了 HU LE) with their
  sub-choice flows (player picker, MING/AN, ANGANG, 包 BAO + 台 TAI
  stepper), a No Win control, host-only "End Game Now", and the
  4-winds-complete continue/end prompt.
- A Mahjong rules form on New Room (per-action dollar amounts, max TAI)
  with three example presets (Casual/Standard/High Stakes) as a starting
  point — not a full named/saved-ruleset system yet, unlike Taidi's.
- New Playwright coverage: a full 4-device hand exercising YAO, GANG, and a
  direct HU with dealer rotation, plus lobby leave/disband for Mahjong
  rooms.

## [0.4.4] - 2026-09-03

Mahjong's API layer (Phase D of the leave/disband + Mahjong plan). Still no
user-visible change — the web app doesn't call any of this yet.

### Added
- `POST /rooms/{id}/mahjong/{join,leave,disband,assign-seats,start,yao,gang,
  hu,no-win,continue-wind,end}` — full HTTP surface for `mahjong_core`,
  mirroring the existing Taidi endpoints' `_dispatch` pattern exactly.
- Every Mahjong action endpoint rejects a Taidi room (400), and every Taidi
  action endpoint now rejects a Mahjong room (400) — previously untested
  since Mahjong rooms didn't exist yet.
- 11 new integration tests against a real Postgres database covering the
  full settlement math end to end over HTTP, seat assignment, host-only
  end/assign-seats, leave/disband, and the final-hand pending-wind-decision
  → continue-wind flow.

## [0.4.3] - 2026-09-03

Mahjong's pure scoring/state engine (ADR-0006) — still no user-visible
change, nothing wired into the API or web app yet. This is Phase C of the
leave/disband + Mahjong plan: the engine gets built and fully tested
standalone before any API or UI work starts, same as `taidi_core` was.

### Added
- `core/mahjong_core/`: event-sourced room/hand state machine for YAO, GANG,
  and HU declarations, dealer/wind rotation (gang-rotates/no-gang-repeats,
  with a win-only-closes rule on the last seat of the last wind), seat
  assignment, and leave/disband — mirroring `taidi_core`'s shape, sharing
  its genuinely game-agnostic pieces (`Member`, `Settlement`, `PlayerStats`,
  the error hierarchy, `minimize_transfers`) rather than duplicating them.
- 60 new tests: fixed-case settlement math for every YAO/GANG/HU/BAO
  variant, Hypothesis invariants checking the settlement-table formulas
  hold for randomized rule values, and dedicated coverage of the dealer/
  wind state machine including the last-seat-of-last-wind edge case.

## [0.4.2] - 2026-09-03

Groundwork for Mahjong as a second game type (ADR-0006) — no user-visible
change yet, the Mahjong tile still shows "Coming soon."

### Added
- `rooms.game_type` column (`taidi` | `mahjong`, defaults to `taidi`),
  threaded through room creation and every state response so the frontend
  can eventually branch on it.

## [0.4.1] - 2026-09-03

There was no way to exit a room once joined, or to cancel one you created —
a real gap once people started actually creating rooms and hitting "wrong
room" or "changed my mind."

### Added
- "Leave Room" for any non-host member and "Disband Room" for the host, both
  lobby-only (leaving/disbanding mid-game is a bigger problem — orphaning an
  in-progress round — and isn't needed to fix this). New `PLAYER_LEFT`/
  `ROOM_DISBANDED` events and a new `disbanded` room status; anyone still
  viewing a disbanded room's lobby gets bounced home on their next poll.

## [0.4.0] - 2026-09-01

Magic links turned out to have real friction in practice: only the
most-recently-requested link works (PKCE overwrites the stored code
verifier on each request), and Supabase's default email sender has a low
built-in rate limit that a round of troubleshooting can burn through
quickly. Email + password removes the email round-trip from sign-in
entirely — email is now used only for account recovery.

### Added
- Email + password sign-up, log-in, and forgot-password (`SupabaseAuthForm`),
  replacing the magic-link form. Sign-up returns a session immediately if
  the Supabase project has "Confirm email" disabled; otherwise the user is
  told to confirm by email before logging in.
- Password reset via a reset-link email: `/auth/callback` now detects
  Supabase's `PASSWORD_RECOVERY` auth event and shows an inline "set a new
  password" form instead of just redirecting home.
- A Settings page (Supabase mode only, linked from Home) for changing
  display name, email, and password, and signing out.
- `lib/account.ts` — `updateDisplayName`/`updateEmail`/`updatePassword`,
  all thin wrappers over `supabase.auth.updateUser`.

### Removed
- `signInWithMagicLink` — dev mode (name-only login) is unaffected.

## [0.3.3] - 2026-09-01

### Fixed
- The "check your email" screen now warns that requesting a new magic
  link invalidates the previous one, instead of leaving users to hit the
  confusing "PKCE code verifier not found in storage" error by clicking
  an older email.
- A failed magic-link send now surfaces the real Supabase error message
  (e.g. "email rate limit exceeded") instead of a generic "try again"
  message that hid the actual cause.

Discovered while actually creating the Supabase project: it uses a JWT
Signing Key (asymmetric), not the shared HS256 secret ADR-0005 assumed.
Supabase has moved newer projects to that model by default.

### Added
- JWKS-based JWT verification (`TAIDI_SUPABASE_URL`, via `PyJWKClient`),
  tried first when configured, falling back to the shared-secret path for
  older projects that still have one. `pyjwt[crypto]` added to `api/`'s
  dependencies — asymmetric algorithms silently don't work without
  `cryptography` installed; caught by the same clean-venv verification
  used for the Render build command, before it could fail in production.
- 5 new tests covering the JWKS path with a real generated EC keypair and
  a monkeypatched `PyJWKClient.fetch_data` (no live network call), plus a
  test proving JWKS wins when both a URL and a legacy secret are set.
- `render.yaml`, `api/.env.example`, and the README's deploy steps updated
  to ask which case a project is in and set the right variable.

## [0.3.2] - 2026-09-01

Groundwork for real accounts and a real deployment (ADR-0005) — Phase 3's
stats and rulesets need an identity that survives across sessions, which
`TAIDI_AUTH_MODE=dev`'s fresh-random-UUID-per-login can't provide.

### Added
- Supabase Auth support end to end: magic-link sign-in (`lib/auth.ts`'s
  `signInWithMagicLink`), an `/auth/callback` route that exchanges the
  emailed code for a session, and a `useStoredUser()`/`getStoredAuth()`
  surface that behaves identically to dev mode for every existing page —
  room/new pages needed zero changes. Display name rides in the JWT's
  `user_metadata`, exactly where the API's `_display_name_from_claims`
  already looked for it since ADR-0003.
- `TAIDI_AUTH_MODE=supabase` on the API: verifies real Supabase-issued
  tokens (checking `aud="authenticated"`, not just skipping audience
  verification as before) against the project's JWT secret. Verified with
  hand-crafted tokens matching Supabase's real claim shape — no project
  needed to prove the logic correct.
- `render.yaml`: a one-click Render Blueprint for the API, verified by
  installing into a genuinely clean virtualenv (not the developer's
  already-populated one) and confirming the server boots and serves.
- `statement_cache_size: 0` on the asyncpg engine — required once
  `TAIDI_DATABASE_URL` points at a pooled connection (e.g. Supabase's
  pgbouncer in transaction mode), harmless otherwise.
- Root README "Deploy the room app" section: the full Supabase → Render →
  Vercel sequence.

### Changed
- Local development is completely unaffected — `TAIDI_AUTH_MODE`/
  `NEXT_PUBLIC_AUTH_MODE` default to `dev` everywhere, and the full test
  and e2e suites were re-run against dev mode after every change in this
  release to confirm zero regression.

## [0.3.1] - 2026-09-01

App renamed to **GamBROle** (multi-game framing — Taidi is the first of
several games it'll host) and the "New Room" flow now matches that: pick a
game, then (for Taidi) configure every rule the old Streamlit app exposed
before the room is created.

### Added
- Rebrand: "GamBROle" across the manifest, page metadata, and home screen;
  new monogram icon (was Taidi's card-specific "2 of spades" mark).
- Home screen now has three post-login actions: New Room, Join Room, and
  My Stats (a real placeholder screen — "feature not available yet" —
  not a dead button).
- `/new`: pick a game (Taidi, Mahjong, Poker). Mahjong and Poker show the
  same not-available placeholder. Taidi shows the full rules editor —
  card value, base cards, double/triple multiplier toggle and thresholds,
  difference payouts, special hands toggle and value — matching every
  field the legacy Streamlit app exposed. The chosen rules travel with the
  room (held client-side until `start_game`, since the room can't apply
  rules until players have joined) and are what the game actually plays
  by, not just cosmetic.
- End-game screen now shows rounds played and a "so-and-so wins with
  $X" callout alongside the final standings, visible to every player's
  device the moment the game ends (already true structurally; this made
  it read as real final stats rather than just a balances list).
- e2e coverage for all of the above, including an exact-value assertion
  (a room created at $1.00/card resolves round 1 to precisely $29.00 for
  the winner) proving the configured rules reach the scoring engine, not
  just that *some* room got created.

### Fixed
- A real hydration bug, not just a test artifact: any returning user with
  a stored session hit `Hydration failed because the server rendered HTML
  didn't match the client` on every page load of `/`, `/new`, and
  `/room/{id}`. Cause: reading `localStorage` in a lazy `useState`
  initializer runs during SSR too (where there's no `window`, so it
  always resolves to "logged out"), while the client's first hydration
  pass resolves the real stored value — a guaranteed mismatch for anyone
  with an existing session. That lazy-init pattern was itself an earlier
  "fix" for an eslint `react-hooks/set-state-in-effect` warning; the
  correct fix was recognizing that a `localStorage` read is exactly the
  "subscribe to an external system" case that rule is meant to allow via
  an effect, not to avoid. Fixed with a shared `useStoredUser()` hook
  that defers the read to an effect and exposes a `checked` flag so
  auth-gated pages don't redirect a real user during the one-tick window
  before the check resolves. Verified via a targeted reload-with-existing-session
  repro (caught the bug, then confirmed clean) in addition to the full suite.

## [0.3.0] - 2026-09-01

Phase 2: the first live-room vertical slice, end to end — a room where
every player acts from their own device, proven by a Playwright test that
drives three separate browser contexts through a full game with no shared
page and no manual refresh.

### Added
- `api/`: a FastAPI backend wrapping `taidi_core` as the sole write path to
  a room's event log (ADR-0003). Endpoints for create/join-by-code/state and
  every room command (start, win, cards, submit-for, special, void, end),
  each mapping `taidi_core.machine`'s `SeqConflict`/`NotAuthorized`/
  `IllegalTransition` to 409/403/400.
- Pluggable auth: `TAIDI_AUTH_MODE=dev` (default) mints local tokens via
  `POST /auth/dev-login` with no external identity provider; `supabase`
  mode verifies against a real Supabase project's JWT secret instead — same
  code path either way.
- Postgres schema (`rooms`, `events`) with `UNIQUE(room_id, seq)` as a
  second concurrency guard beneath the state machine's own check; Alembic
  migrations targeting `TAIDI_DATABASE_URL` directly.
- `docker-compose.yml`: an isolated local Postgres (project `taidi`, port
  5433) — no cloud account needed for local development.
- `web/`: a Next.js PWA — dev sign-in, new room / join by code, a lobby
  that converges as players join, and a live table (Win, per-player card
  entry, special hands settling immediately, end game), all driven by
  polling `GET /rooms/{id}/state` as a deliberate, swappable stand-in for
  Supabase Realtime (ADR-0004).
- `e2e/full-game.spec.ts`: three independent browser contexts play a full
  game through the real UI against the real API and a real database —
  the actual proof of this phase's "two phones" bar.
- 10 API integration tests (real Postgres, incl. a concurrency test with
  `asyncio.gather` against real HTTP requests) + the e2e suite. `mypy
  --strict` clean on both Python packages; CI runs a Postgres service, an
  Alembic upgrade/downgrade/upgrade round-trip, and the full Playwright
  suite on every push.
- `core/taidi_core` is now PEP 561 typed (`py.typed`) so consuming packages'
  `mypy --strict` runs pick up its inline types automatically.

### Fixed
- A command's own 409 conflict was being treated as failure, discarding
  the player's in-flight action (e.g. their card count) even when it had
  nothing to do with the conflict. Every command now retries once against
  the fresh state before surfacing an error — caught by the three-device
  Playwright test, which failed until this was in place.
- (backend, before release) `_as_json`'s own body was accidentally
  overwritten into a call to itself during a find-and-replace, causing
  infinite recursion on every response; caught immediately by the existing
  test suite.

## [0.2.0] - 2026-09-01

Phase 1 of the roadmap: `taidi_core`, a standalone, pure-Python domain
package implementing the multiplayer room design from ADR-0001. Not yet
wired into the deployed Streamlit app — this release proves the design in
isolation, with its own test suite and CI job.

### Added
- `core/taidi_core`: typed models (`GameRules`, `Transfer`, `RoundState`,
  `RoomState`, `Event`, `PlayerStats`, `Settlement`), the scoring engine
  (`rules.py`, integer cents), the room/round state machine (`machine.py`:
  `join_player`, `start_game`, `claim_win`, `submit_cards`, `submit_for`,
  `add_special_hand`, `void_last_round`, `end_game`, `apply`, `fold`),
  lifetime stats (`stats.py`), and settlement (`settlement.py`: pairwise
  netting and greedy debt minimization).
- 45 tests for the core package: golden fixtures per rule toggle, hypothesis
  property tests (zero-sum, winner-never-pays, determinism), and full state
  machine coverage including a flagship full-simulated-game test and a
  replay-from-scratch determinism test. `mypy --strict` passes.
- `scripts/migrate_legacy_to_events.py`: reconstructs raw round inputs from
  legacy archived-game transfers and replays them through `taidi_core`,
  verifying the resulting balances match the original totals to within a
  couple of cents (float-accumulation tolerance).
- ADR-0002: pure Python core package, integer cents, UUID player identity.
- CI now also runs the core package's tests and `mypy --strict` on every push.

### Fixed
- (in `taidi_core`, not the legacy engine) voiding a round no longer
  reverses special-hand transfers claimed during it — special hands settle
  independently of round resolution and must survive an undo.

## [0.1.0] - 2026-09-01

First versioned release of the Streamlit scorekeeper app.

### Added
- Home-screen navigation: New Game, Continue Game, Analytics, Settings.
- Fully configurable rules (card value, base payout, double/triple thresholds,
  difference payouts, special hands) and saved rulesets.
- Autosaving games with undo, continue-later, and explicit finish.
- Lifetime analytics: leaderboard, per-player profit/loss trend, per-game history.
- Player management: add, rename (propagates through all games), remove.
- Game management: edit balances/rules of ongoing games, edit totals of
  finished games, delete either.
- Persistence in SQLite locally or Turso in the cloud.
- Optional shared passcode gate (`APP_PASSCODE`).
- JSON backup export and restore.
- Test suite and GitHub Actions CI (ruff + pytest).
