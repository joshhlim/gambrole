# ADR-0001: Event-sourced multiplayer rooms

- Status: accepted
- Date: 2026-09-01

## Context

GamBROle began as a single-scorekeeper Streamlit app called Taidi Tracker: one person enters
every player's remaining cards each round, and the whole game is saved as a
JSON snapshot after each submission. The product direction is a **multiplayer
room** where each player acts from their own phone:

- the winner taps *Win*, every other player enters their own cards, and the
  round resolves automatically once all inputs are in;
- anyone can add a *special hand* at any time;
- anyone can end the game; results flow into each player's own statistics;
- players later settle debts with each other and confirm payments.

Whole-snapshot saves cannot support this: concurrent input from several
devices is last-write-wins, there is no way to know which inputs are still
outstanding, and undo/audit require re-deriving intent from computed outputs.

## Decision

1. **Rooms are event-sourced.** A room is an append-only log of events with a
   per-room monotonic `seq`. Current state (round phase, outstanding inputs,
   balances) is derived by replaying events through pure functions in
   `taidi_core.machine`.
2. **A round is a state machine**: `playing → collecting (win claimed) →
   resolved`, then the next round starts. The event vocabulary is
   `player_joined, game_started, win_claimed, cards_submitted, special_hand,
   round_resolved, round_voided, submitted_for, game_ended`.
3. **Inputs are truth, transfers are cache.** Each resolved round stores the
   raw inputs (card counts, special-hand counts), the rules in force, the
   engine version, and the computed transfers. A CI test replays every round
   and asserts the cached transfers match.
4. **Optimistic concurrency.** Every command carries `expected_seq`; a stale
   command is rejected with 409 and the current state. Conflicts are shown to
   the user, never merged. Client-generated event ids make retries idempotent.
5. **Nothing is deleted.** Undo and corrections are new events
   (`round_voided`, `submitted_for`); the host has override powers for every
   player action and a short reopen window after `game_ended`.
6. **Single write path.** Only the API writes events, after validating the
   command against the state machine. Clients subscribe to the event stream
   (Supabase Realtime) for fan-out; the API holds no connection state.
7. **Money is integer cents; players are identified by id, not name.**

## Consequences

- The scoring engine stays pure and testable in Python and is reused
  unchanged by the API.
- Multi-device input, "waiting for Bob" indicators, undo, audit trails, and
  future analytics (per-round data, head-to-head) all fall out of the log.
- Replay cost grows with game length; a materialised `rounds` read model keeps
  reads fast. Games are short (tens of rounds), so this is not a concern.
- The current Streamlit app's snapshots must be migrated into events; raw card
  counts are recoverable from stored transfers, so a tested one-off script is
  sufficient.
