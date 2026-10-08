"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { UserProfile } from "./friendsTypes";
import { profileApi } from "./profileApi";

// Photos and accents for players shown by id (a table, a debt). Asked for
// once per player per page load — a room polls every 1.5s, and its members
// never change their faces mid-hand. null marks an id the API doesn't know
// as an account (a guest), so it isn't asked about again.

const cache = new Map<string, UserProfile | null>();
const pending = new Set<string>();
const listeners = new Set<() => void>();
let version = 0;

function emit() {
  version++;
  for (const l of listeners) l();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Seeds the cache from a list that already carries profiles (friends,
 * group members), so a later table lookup doesn't ask again. */
export function rememberProfiles(profiles: UserProfile[]): void {
  for (const p of profiles) cache.set(p.user_id, p);
  if (profiles.length) emit();
}

/** Forgets one player — after your own photo or accent changes. */
export function forgetProfile(userId: string): void {
  if (cache.delete(userId)) emit();
}

async function fetchMissing(ids: string[]) {
  const missing = ids.filter((id) => !cache.has(id) && !pending.has(id));
  if (missing.length === 0) return;
  for (const id of missing) pending.add(id);
  try {
    // The API takes at most 50 a time.
    for (let i = 0; i < missing.length; i += 50) {
      const chunk = missing.slice(i, i + 50);
      const found = await profileApi.profiles(chunk);
      for (const id of chunk) cache.set(id, found[id] ?? null);
    }
    emit();
  } catch {
    /* initials it is — and the next mount can try again */
  } finally {
    for (const id of missing) pending.delete(id);
  }
}

/**
 * Profiles for these player ids, keyed by id; absent until loaded and for
 * guests. Pass every id you'll show — the request covers whatever isn't
 * cached yet, in one go.
 */
export function useProfiles(ids: string[]): Record<string, UserProfile> {
  // A stable key, so a poll that hands over a new array of the same ids
  // doesn't refire the effect.
  const key = [...new Set(ids)].sort().join(",");
  useSyncExternalStore(subscribe, () => version, () => 0);
  useEffect(() => {
    if (key) fetchMissing(key.split(","));
  }, [key]);
  const out: Record<string, UserProfile> = {};
  for (const id of key ? key.split(",") : []) {
    const p = cache.get(id);
    if (p) out[id] = p;
  }
  return out;
}
