"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useStoredUser } from "./auth";
import { friendsApi } from "./friendsApi";
import type { MyProfile } from "./friendsTypes";

// Your own profile, held once for the whole app: the top bar, Settings,
// /new's saved defaults, onboarding and the theme sync all read the same
// copy, and anything that changes it (every profile endpoint answers with
// the whole profile) hands the result to setMe so all of them update.

let current: MyProfile | null = null;
let inflight: { userId: string; promise: Promise<MyProfile> } | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = () => current;

export function setMe(profile: MyProfile | null): void {
  current = profile;
  emit();
}

/** Fetches your profile, sharing one request between everyone asking at
 * once. `force` refetches even when it's already held. */
export function loadMe(userId: string, force = false): Promise<MyProfile> {
  if (!force && current?.user_id === userId) return Promise.resolve(current);
  if (inflight && inflight.userId === userId) return inflight.promise;
  const promise = friendsApi
    .me()
    .then((p) => {
      // A different account may have signed in while this was out.
      if (inflight?.promise === promise) setMe(p);
      return p;
    })
    .finally(() => {
      if (inflight?.promise === promise) inflight = null;
    });
  inflight = { userId, promise };
  return promise;
}

/**
 * Your profile, or null until it's loaded (or when signed out). Never hands
 * one account's profile to another signed in after it on the same phone.
 */
export function useMe(): MyProfile | null {
  const { user } = useStoredUser();
  const me = useSyncExternalStore(subscribe, snapshot, () => null);
  const userId = user?.user_id ?? null;
  useEffect(() => {
    if (!userId) return;
    loadMe(userId).catch(() => {
      /* each caller copes with null */
    });
  }, [userId]);
  return me && me.user_id === userId ? me : null;
}
