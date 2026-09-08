# Progress / session handoff

Read this first in a new session. It's a living snapshot of where the
project stands and the non-obvious decisions behind it — CHANGELOG.md has
the chronological record, `docs/adr/` has the architecture reasoning, this
file is "what's true right now and what to know before touching it."

**Keep this updated**: when you (Claude) finish a chunk of work in a
session, update the relevant section here before signing off, the same way
CHANGELOG.md gets a new entry. Don't let it go stale.

## Current state (as of 2026-09-08, v0.6.1)

Real stack is live: Supabase (Postgres + auth) + Render (API) + Vercel
(web), deployed as **gambrole.vercel.app**, auto-deploying from every push
to `main`. Two playable games: **Taidi** (Big Two) and **Mahjong**, both
fully wired lobby → live table → ended-game stats, plus an **analytics
dashboard** (`/stats`, v0.6.0) with a combined overview and per-game
detail tabs. Local dev servers run at `localhost:3100` (web) and
`localhost:8000` (API).

**Project renamed 2026-09-08**: GitHub repo is now `joshhlim/gambrole`
(was `joshhlim/taidi`), local clone is `/Users/joshlim/gambrole` (was
`/Users/joshlim/taidi`), Python distribution package names are
`gambrole-core`/`gambrole-api`/`gambrole-web` (the actual importable
`taidi_core` module keeps its name — it's the Big Two game engine
specifically, not the product). `TAIDI_*` env var names, Render/Vercel/
Supabase config, and the legacy Streamlit app were deliberately left
alone — that's a separate, manually-coordinated step, not done yet.

Legacy: `taidi.py` (Streamlit + SQLite/Turso) is a separate older app,
still deployed independently, not part of the `core/`/`api`/`web` stack.

## Mahjong — full rules reference

This is the newer, more custom-rules-heavy of the two games, built this
project phase (ADR-0006: a parallel `mahjong_core` package, not a
refactor of `taidi_core`'s closed `EventType` switch). Money is in
**chips**, tracked as net balance per player; a player's displayed chip
stack is `rules.base_chips + balances[player_id]`.

### Table setup
- Exactly 4 players, seats 0-3 nicknamed 東 DONG / 南 NAN / 西 XI / 北 BEI
  (frontend-only labels — the backend only ever sees seat ints). Seats
  default to join order; the host can rearrange them (tap two players to
  swap) before starting, lobby-only.
- Live table view is a diamond around the table: you at the bottom, the
  next seat clockwise on your right, the previous seat on your left, the
  opposite seat at the top. A center badge shows a 2-character wind+dealer
  glyph (`SEAT_LABELS[(wind-1)%4].han + SEAT_LABELS[dealer_seat].han`,
  e.g. 東東 for wind 1 dealer-seat 1, 西南 for wind 3 dealer-seat 2). The
  dealer's card gets a gold border/background; your own card is tagged
  "(you)" — both can appear on the same card. Cards are a fixed size
  regardless of display-name length.

### Actions (咬 YAO / 槓 GANG / 胡了 HU LE)
| Action | Choice | Settlement |
|---|---|---|
| YAO | self | each of other 3 pays `yao_chips × (2 if AN else 1)` |
| YAO | another seat | that seat pays `yao_chips × (2 if AN else 1)` |
| GANG | self | each of other 3 pays `gang_chips × 1` |
| GANG | another seat | that seat pays `gang_chips × 3` |
| GANG | ANGANG (暗槓) | each of other 3 pays `gang_chips × 2` |
| HU | zimo (self) | each of other 3 pays `tai_table[tai].zimo` |
| HU | direct (another seat) | that seat pays `tai_table[tai].hu` |
| HU | bao (包, a designated covering seat) | that seat alone pays `tai_table[tai].zimo × 3` |

`tai_table` is a **non-linear per-tai lookup** (`{hu, zimo}` per level,
1..`max_tai`), not a rate × tai — real stakes tables aren't linear (a
5-tai hand pays far more than 5× a 1-tai hand).

**Optional HU bonuses**, both flat chip amounts, both default to 0 (off),
both toggled per-declaration and independent of each other and of BAO:
- `zimo_bonus_chips`: only on a self-drawn (zimo) win — each of the other
  3 pays this extra amount on top of the zimo tai payout. Rejected if the
  win isn't zimo.
- `klppdd_chips`: on *any* win. Mirrors whichever payer structure the win
  already uses — split 3 ways (each pays `klppdd_chips`) on a zimo win;
  paid in full (`klppdd_chips × 3`) by the single payer on a direct or
  bao win.

**Presets** (New Room form): "3/6 半" (base 300, yao 2, gang 2, tai 1-5:
hu 4/7/11/20/40, zimo 4/5/7/12/22) and "5/1 半" (base 500, yao 3, gang 3,
zimo bonus 5, klppdd 5, tai 1-7: hu 4/8/16/32/64/128/256, zimo
2/4/8/16/32/64/128). More presets are likely to be requested — ask for
exact numbers rather than inventing them.

### Dealer / wind rotation — custom rule, gotten wrong once already

This is **not** standard mahjong and was corrected once already (v0.5.4)
after an initial gang-driven implementation didn't match intent. The
current, confirmed-correct rule:

- **On a WIN** (not the last seat of the last wind): dealer stays if the
  dealer themselves won; rotates to the next seat otherwise. **Gang
  presence is irrelevant to a win** — don't reintroduce gang-checking here.
- **On a NO WIN**: dealer stays unless a gang happened that hand (by
  anyone, any kind), in which case it still rotates.
- Either way, wrapping seat 3→0 advances the wind. 4 winds total.
- **Last seat of the last wind** (wind 4, dealer seat 3 / 北) is a special
  case: only a **WIN** closes the 4-wind cycle (regardless of who won,
  gang or not) — a no-win there just repeats the same dealer/wind. Cycle
  completion sets `pending_wind_decision`; only the host's `continue_wind`
  (starts wind+1 at seat 0) or `end_game` can proceed from there.
  "Continue" past 4 winds just keeps incrementing (wind 5, 6, ...),
  re-prompting at each subsequent last-seat-of-wind boundary.

Implementation: `core/mahjong_core/machine.py`'s `_plan_hand_close(hand,
*, is_win, should_rotate)` — `should_rotate` is computed by the caller
(`declare_hu`: `winner's seat != hand.dealer_seat`; `declare_no_win`:
`hand.had_gang`), not by `_plan_hand_close` itself, so each close path can
apply its own rule. The outcome is folded into the closing event's payload
at command time, so replay never recomputes it — safe to change the rule
again later without touching history.

### Key files
- `core/mahjong_core/models.py` — `MahjongRules`, `TaiPayout`, `RoomState`, events
- `core/mahjong_core/rules.py` — pure money-math functions (`ENGINE_VERSION = "mahjong-3"`)
- `core/mahjong_core/machine.py` — the state machine, dealer/wind logic
- `api/app/routers/mahjong.py` + `api/app/schemas.py` — HTTP layer
- `web/src/lib/mahjongTypes.ts`, `mahjongApi.ts` — frontend types/client
- `web/src/app/room/[roomId]/MahjongRoom.tsx` — the live table UI
- `web/src/app/new/page.tsx` — rules form + presets
- `web/e2e/mahjong-game.spec.ts` — 4-device Playwright coverage

## Architecture (see docs/adr/ for full reasoning)

- **Event-sourced rooms**: append-only event log, `apply()`/`fold()` are
  pure, `expected_seq` gives optimistic concurrency. Commands
  validate-then-return-events, never mutate directly.
- **Two parallel core packages**, one `gambrole-core` distribution:
  `taidi_core` (Taidi/Big Two) and `mahjong_core` (Mahjong), each with
  their own `EventType`, state shape, `machine.py` — deliberately *not*
  unified into one generic dispatcher (ADR-0006). Genuinely game-agnostic
  pieces (`Member`, `Settlement`, `PlayerStats`, `RoomStatus`, the
  `MachineError` hierarchy, `minimize_transfers`) are imported from
  `taidi_core` into `mahjong_core` rather than duplicated.
- **API**: `rooms.game_type` column (`"taidi"|"mahjong"`) picks which core
  package a room folds through. `routers/rooms.py` (Taidi) and
  `routers/mahjong.py` (Mahjong) are fully separate routers sharing only
  `create`/`by-code`/`get-state`.
- **Frontend**: `room/[roomId]/page.tsx` does one small untyped fetch to
  learn `game_type`, then mounts `TaidiRoom` or `MahjongRoom`.
  `usePolling` (1.5s) stands in for realtime. A `run()` wrapper retries
  once on 409 by resyncing to the server's returned state.

## Conventions to follow

- **Bash + venv**: the Bash tool doesn't share shell state across calls —
  `source .venv/bin/activate && <command>` must happen in one call, or use
  `.venv/bin/python` / `.venv/bin/pytest` / `.venv/bin/mypy` /
  `.venv/bin/ruff` directly. Same for `npx playwright test` — `cd web`
  first in the same command, or `npx` silently resolves to a different,
  freshly-downloaded `playwright` package and every test fails with a
  confusing "did not expect test() to be called here" error.
- **Testing depth expected for engine/money-math changes**: fixed-case
  tests in `core/tests/test_mahjong_machine.py`, Hypothesis property tests
  in `core/tests/test_mahjong_engine_properties.py`, golden fixtures for
  real preset numbers in `core/tests/test_mahjong_rules_fixtures.py`, API
  integration tests against real Postgres in `api/tests/test_mahjong_api.py`,
  and a Playwright scenario in `web/e2e/mahjong-game.spec.ts` if the change
  is user-visible. This project's whole Mahjong build was verified this way
  layer by layer before wiring the next layer on top.
- **CHANGELOG.md**: add an entry per logical increment (Keep a Changelog
  format). Git tags are only cut after the user verifies functionality
  live — not automatically.
- **Commit/push**: this session's practice has been to commit+push after
  each completed, tested increment without waiting to be asked, and to
  watch CI (`gh run watch <id> --exit-status`) until green before reporting
  done.
- **UI style**: no emojis, no explainer/marketing copy, custom minimal
  Tailwind components (no component library). Bilingual Chinese+pinyin
  labels for Mahjong action buttons (咬 YAO, 暗咬 ANYAO, 胡了 HU LE, 槓
  GANG, 暗槓 ANGANG, 台 TAI, 東/南/西/北 DONG/NAN/XI/BEI, 包 BAO).

## Known pending / likely next

- More Mahjong presets are likely to be requested (user said "let's start
  digging into the presets and the values", plural) — ask for exact
  numbers, don't invent them.
- Email SMTP rate limit needs sorting before a real game night (Supabase's
  default email sending has low limits — noted as a pre-launch blocker,
  not yet actioned as of this writing).
- Pre-existing rooms (created before the 2026-09-08 stats-infra migration)
  won't show up in `/stats/me` until `api/scripts/backfill_stats_infra.py`
  runs once against the production database — not yet run; needs the
  user's go-ahead since it touches live data.
- The 2026-09-08 rename to GamBROle was deliberately scoped to repo/code/
  docs only. If the user wants it to go further: `TAIDI_*` env var names
  would need renaming in `render.yaml` *and* Render's dashboard (in
  lockstep, to avoid an outage), and the legacy Streamlit app
  (`taidi.py`/`db.py`/`ui.py`/`game.py`/`taidi.db`) would need renaming
  plus a matching update to Streamlit Community Cloud's app settings —
  neither was requested yet.
- No known open bugs. Everything shipped through v0.6.1 is tested and
  CI-green.
