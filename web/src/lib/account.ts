"use client";

import { request } from "./api";
import {
  getStoredAuth,
  isLocalAuth,
  localAuthRequest,
  storeLocalSession,
  supabase,
} from "./auth";

/** All three trigger Supabase's USER_UPDATED auth event, which the existing
 * onAuthStateChange listeners in auth.ts already react to — so a change
 * here shows up immediately anywhere useStoredUser() is used, with no
 * extra wiring. Used by both the Settings page and, for password, the
 * password-recovery flow in /auth/callback.
 *
 * In local mode each goes to the API instead, which hands back a fresh
 * token (the old one carries the old name and address); storing it
 * announces the change the same way dev-mode sign-in does. */

async function updateLocalAccount(changes: Record<string, string>): Promise<void> {
  const res = await localAuthRequest("PATCH", "/me", changes, getStoredAuth()?.token);
  storeLocalSession(await res.json());
}

export async function updateDisplayName(name: string): Promise<void> {
  if (isLocalAuth()) return updateLocalAccount({ display_name: name });
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { error } = await supabase.auth.updateUser({ data: { display_name: name } });
  if (error) throw error;
}

/** Supabase emails a confirmation link to the new address before this
 * takes effect (and, if "Secure email change" is on, to the old one too).
 * Local mode applies it immediately. */
export async function updateEmail(newEmail: string): Promise<void> {
  if (isLocalAuth()) return updateLocalAccount({ email: newEmail });
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { error } = await supabase.auth.updateUser({ email: newEmail });
  if (error) throw error;
}

export async function updatePassword(newPassword: string): Promise<void> {
  if (isLocalAuth()) return updateLocalAccount({ password: newPassword });
  if (!supabase) throw new Error("Supabase auth is not configured.");
  const { error } = await supabase.auth.updateUser({ password: newPassword });
  if (error) throw error;
}

/** The signed-in account's email address, for Settings. */
export async function getAccountEmail(): Promise<string | null> {
  if (isLocalAuth()) {
    const me = await request<{ email: string | null }>("/users/me");
    return me.email;
  }
  if (!supabase) return null;
  const { data } = await supabase.auth.getUser();
  return data.user?.email ?? null;
}
