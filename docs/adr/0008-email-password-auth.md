# ADR-0008: Email + password sign-in replaces magic links

- Status: accepted
- Date: 2026-09-28 (records a change shipped 2026-09-01 in commit `f7226fd`)
- Supersedes: ADR-0005 decision 1 (magic-link-only auth) and the
  `signInWithOtp` detail in decision 4; also the "default to `dev`" part of
  decision 3

## Context

ADR-0005 chose Supabase magic links as the only sign-in method: zero extra
setup, no password storage. In use it was the wrong trade for a party-game
app. Every sign-in round-tripped through email on someone's phone at the
table, and Supabase's built-in email sender is rate-limited to a handful of
messages an hour — a game night with several new players could exhaust it
before everyone was in.

Separately, `TAIDI_AUTH_MODE` defaulting to `dev` meant a deploy that lost
the variable would silently start accepting self-minted dev tokens.

## Decision

1. **Email + password via Supabase Auth** (`signUp` / `signInWithPassword`).
   The display name still rides in `user_metadata` (now set at sign-up via
   `signUp({ options: { data: { display_name } } })`), so the API's
   `_display_name_from_claims` needed no change. JWT verification (JWKS or
   legacy secret, ADR-0005's update) is unchanged.
2. **Email is only used for recovery.** "Forgot password" sends a reset link
   (`resetPasswordForEmail`) back to `/auth/callback`, which detects
   Supabase's `PASSWORD_RECOVERY` event and asks for a new password instead
   of just signing in. With "Confirm email" disabled in Supabase (as
   recommended in the README), sign-up needs no email at all.
3. **A Settings page** (Supabase mode only) changes display name, email, and
   password via `updateUser`, and signs out.
4. **`TAIDI_AUTH_MODE` has no default.** The API refuses to start unless it
   is explicitly `dev` or `supabase`. Render sets `supabase` in
   `render.yaml`; CI and local development set `dev`. The web side's
   `NEXT_PUBLIC_AUTH_MODE` is unchanged.

Google OAuth remains out of scope for the same reason as ADR-0005.

## Consequences

- Sign-in no longer depends on email delivery, so the email rate limit only
  affects password resets and email changes.
- The app now holds passwords, via Supabase — none of it touches our API or
  database; the API still only ever sees a signed JWT.
- The magic-link redirect URL in Supabase is still needed, now for password
  resets and email-change confirmations.
- A missing or misspelled `TAIDI_AUTH_MODE` fails a deploy loudly instead of
  opening a dev-token backdoor.
