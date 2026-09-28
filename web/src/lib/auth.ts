"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { Session, User } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

import { API_URL, API_URL_MISSING } from "./config";

const TOKEN_KEY = "taidi_token";
const USER_KEY = "taidi_user";

// Storage can throw outright (Safari private mode, blocked site data), and
// a throw here would take sign-in down with it — so every access degrades
// to "nothing stored" instead.
function storageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* signed in for this page load only */
  }
}

function storageRemove(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* nothing to clear */
  }
}

// "dev" (the default, used locally): the app's own POST /auth/dev-login
// mints a token for any name, no external provider. "supabase": real
// accounts via Supabase Auth (magic link). Whichever is active, everything
// below getStoredAuth() behaves identically to the rest of the app.
const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "dev";
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabase =
  AUTH_MODE === "supabase" && SUPABASE_URL && SUPABASE_ANON_KEY
    ? createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY)
    : null;

export interface CurrentUser {
  user_id: string;
  display_name: string;
}

export interface StoredAuth {
  token: string;
  user: CurrentUser;
}

function supabaseUserToCurrentUser(user: User): CurrentUser {
  const displayName =
    (user.user_metadata?.display_name as string | undefined) ||
    user.email ||
    "Player";
  return { user_id: user.id, display_name: displayName };
}

function supabaseSessionToStoredAuth(
  session: Session | null,
): StoredAuth | null {
  return session
    ? {
        token: session.access_token,
        user: supabaseUserToCurrentUser(session.user),
      }
    : null;
}

// api.ts reads the bearer token synchronously on every request, but
// Supabase's session is only available async (getSession() returns a
// Promise). This cache — kept current via onAuthStateChange — is what lets
// getStoredAuth() stay a plain synchronous function either way.
let cachedSupabaseAuth: StoredAuth | null = null;
// The client exchanges a reset link's ?code= itself while initialising and
// announces PASSWORD_RECOVERY once, possibly before /auth/callback has
// mounted to hear it. Registered here, at client creation, it can't be
// missed; the callback page reads it back via wasPasswordRecovery().
let passwordRecovery = false;
supabase?.auth.onAuthStateChange((event, session) => {
  cachedSupabaseAuth = supabaseSessionToStoredAuth(session);
  if (event === "PASSWORD_RECOVERY") passwordRecovery = true;
});

export function wasPasswordRecovery(): boolean {
  return passwordRecovery;
}

/**
 * The bearer token for the next request. In Supabase mode this asks the
 * client rather than trusting the cache: getSession() refreshes a token
 * that's about to expire, where the cache would hand back a dead one after
 * the phone has sat locked through an hour-long hand.
 */
export async function getAccessToken(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    cachedSupabaseAuth = supabaseSessionToStoredAuth(data.session);
    return data.session?.access_token ?? null;
  }
  return getStoredAuth()?.token ?? null;
}

/** Forces a new token after the API refused one. Dev tokens can't be
 * refreshed — null means "retrying won't help". */
export async function refreshAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data, error } = await supabase.auth.refreshSession();
  if (error) return null;
  cachedSupabaseAuth = supabaseSessionToStoredAuth(data.session);
  return data.session?.access_token ?? null;
}

export function getStoredAuth(): StoredAuth | null {
  if (supabase) return cachedSupabaseAuth;
  if (typeof window === "undefined") return null;
  const token = storageGet(TOKEN_KEY);
  const rawUser = storageGet(USER_KEY);
  if (!token || !rawUser) return null;
  try {
    return { token, user: JSON.parse(rawUser) as CurrentUser };
  } catch {
    return null;
  }
}

/**
 * Dev mode's answer to Supabase's `onAuthStateChange`. localStorage writes
 * are invisible to the tab that makes them, which didn't matter while each
 * signed-in screen owned its own copy of the user — but the top bar now
 * outlives every navigation, so signing out has to reach it.
 */
const AUTH_EVENT = "gambrole:auth";

function announceAuthChange(): void {
  window.dispatchEvent(new Event(AUTH_EVENT));
}

/** Dev mode only — Supabase manages its own persistence via cookies. */
export function storeAuth(auth: StoredAuth): void {
  storageSet(TOKEN_KEY, auth.token);
  storageSet(USER_KEY, JSON.stringify(auth.user));
  announceAuthChange();
}

export async function signOut(): Promise<void> {
  if (supabase) {
    // A global sign-out has to reach Supabase to revoke the refresh token.
    // Offline (or with Supabase down) that fails — and must not leave you
    // signed in on this device, so fall back to just dropping the local
    // session.
    try {
      const { error } = await supabase.auth.signOut();
      if (!error) return;
    } catch {
      /* fall through */
    }
    await supabase.auth.signOut({ scope: "local" });
    return;
  }
  storageRemove(TOKEN_KEY);
  storageRemove(USER_KEY);
  announceAuthChange();
}

export interface AuthCheck {
  user: CurrentUser | null;
  /** False until the client-only auth read has actually run. Consumers
   * that redirect on `!user` MUST wait for this — otherwise a genuinely
   * signed-in user gets bounced during the window before it resolves. */
  checked: boolean;
}

/**
 * Read-only access to the signed-in user, safe for SSR.
 *
 * A lazy `useState(() => getStoredAuth()?.user)` initializer looks
 * tempting but is wrong here: it runs during the server render too, where
 * there's no `window` and it always resolves to null, while the client's
 * *first hydration render* would resolve to the real stored user whenever
 * one already exists — a mismatch React has to discard and re-render for.
 * Deferring the read to an effect keeps server and first-client-render
 * identical (both null), then updates once mounted. This is exactly the
 * "subscribe to an external system" case react-hooks/set-state-in-effect
 * is meant to allow, not the derived-state case it warns about.
 */
export function useStoredUser(): AuthCheck {
  const [state, setState] = useState<AuthCheck>({ user: null, checked: false });
  useEffect(() => {
    if (supabase) {
      let cancelled = false;
      supabase.auth.getSession().then(({ data }) => {
        if (cancelled) return;
        const auth = supabaseSessionToStoredAuth(data.session);
        cachedSupabaseAuth = auth;
        setState({ user: auth?.user ?? null, checked: true });
      });
      const { data: sub } = supabase.auth.onAuthStateChange(
        (_event, session) => {
          const auth = supabaseSessionToStoredAuth(session);
          cachedSupabaseAuth = auth;
          setState({ user: auth?.user ?? null, checked: true });
        },
      );
      return () => {
        cancelled = true;
        sub.subscription.unsubscribe();
      };
    }
    const read = () =>
      setState({ user: getStoredAuth()?.user ?? null, checked: true });
    read();
    window.addEventListener(AUTH_EVENT, read);
    return () => window.removeEventListener(AUTH_EVENT, read);
  }, []);
  return state;
}

/**
 * Dev-mode login only (TAIDI_AUTH_MODE=dev on the API) — mints a token for
 * any display name, no external identity provider.
 */
export async function devLogin(displayName: string): Promise<StoredAuth> {
  if (!API_URL) throw new Error(API_URL_MISSING);
  const res = await fetch(`${API_URL}/auth/dev-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (!res.ok) {
    throw new Error(`Login failed: ${res.status}`);
  }
  const data = await res.json();
  const auth: StoredAuth = {
    token: data.access_token,
    user: { user_id: data.user_id, display_name: data.display_name },
  };
  storeAuth(auth);
  return auth;
}

/**
 * Supabase mode: create an account with email + password. `displayName`
 * rides along in `options.data`, which Supabase stores as the user's
 * `user_metadata` — exactly where the API's `_display_name_from_claims`
 * already looks for it (see api/app/auth.py), so no backend change was
 * needed for this.
 *
 * Returns null if the project has "Confirm email" enabled — the account
 * exists but can't sign in until the confirmation link is clicked. With it
 * disabled (recommended for this app — see README), a session comes back
 * immediately and the caller is signed in with no email step at all.
 */
export async function signUpWithPassword(
  email: string,
  password: string,
  displayName: string,
): Promise<StoredAuth | null> {
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: { data: { display_name: displayName } },
  });
  if (error) throw error;
  return supabaseSessionToStoredAuth(data.session);
}

export async function signInWithPassword(
  email: string,
  password: string,
): Promise<StoredAuth> {
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { data, error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });
  if (error) throw error;
  const auth = supabaseSessionToStoredAuth(data.session);
  if (!auth) throw new Error("Sign-in did not return a session.");
  return auth;
}

/** Emails a reset link. Supabase fires a PASSWORD_RECOVERY auth event when
 * the link is clicked — /auth/callback listens for it and prompts for a
 * new password instead of just signing the user in. */
export async function requestPasswordReset(email: string): Promise<void> {
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/auth/callback`,
  });
  if (error) throw error;
}
