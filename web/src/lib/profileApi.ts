"use client";

import { put, request, upload, post } from "./api";
import type {
  MyProfile,
  Preferences,
  ProfileVisibility,
  PublicProfile,
  StatsVisibility,
  UserProfile,
} from "./friendsTypes";
import type { MahjongRules } from "./mahjongTypes";
import type { GameRules } from "./types";

const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

/** Partial: only what's sent changes. A null rule set clears that game's
 * saved default. */
export interface PreferencesUpdate {
  theme?: Preferences["theme"];
  onboarded?: boolean;
  currency_symbol?: string;
  default_rules?: { taidi?: GameRules | null; mahjong?: MahjongRules | null };
}

// Everything that changes your own profile answers with the whole of it, so
// the caller can hand it straight to setMe().
export const profileApi = {
  /** "" clears a field. */
  update: (changes: { bio?: string; city?: string; accent?: string }) =>
    request<MyProfile>("/users/me/profile", { method: "PATCH", body: JSON.stringify(changes) }),
  /** Already square and small — see lib/image.ts. */
  setAvatar: (image: Blob) => upload<MyProfile>("/users/me/avatar", image),
  removeAvatar: () => del<MyProfile>("/users/me/avatar"),
  setPreferences: (changes: PreferencesUpdate) => put<MyProfile>("/users/me/preferences", changes),
  setPrivacy: (changes: {
    profile_visibility?: ProfileVisibility;
    stats_visibility?: StatsVisibility;
    searchable?: boolean;
  }) => put<MyProfile>("/users/me/privacy", changes),
  /** Photos and accents for a set of players. Guests and unknown ids are
   * simply absent. Use useProfiles() rather than calling this per render. */
  profiles: (ids: string[]) => post<Record<string, UserProfile>>("/users/profiles", { ids }),
  /** By username or user id — see profileHref. */
  get: (handle: string) =>
    request<PublicProfile>(
      UUID_RE.test(handle)
        ? `/users/${handle}/profile`
        : `/users/by-username/${encodeURIComponent(handle)}/profile`,
    ),
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Where someone's profile page is. The username when there is one — it's
 * what people share — else the id. The two can't collide: a username is
 * [a-z0-9_] only, and an id always has hyphens.
 */
export function profileHref(u: { user_id: string; username?: string | null }): string {
  return `/u/${u.username ?? u.user_id}`;
}
