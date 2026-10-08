// Mirrors api/app/friends_service.py and users_service.py. Note the absence
// of email on UserProfile: the API never discloses one.

import type { MahjongRules } from "./mahjongTypes";
import type { GameRules } from "./types";

export const ACCENTS = [
  "jade",
  "gold",
  "ruby",
  "sapphire",
  "amethyst",
  "slate",
  "coral",
  "teal",
] as const;
export type Accent = (typeof ACCENTS)[number];

export interface UserProfile {
  user_id: string;
  display_name: string;
  username: string | null;
  /** Relative to API_URL; null when there's no photo. */
  avatar_url?: string | null;
  /** One of ACCENTS, or null for none. A string here because an older or
   * newer API could send one this build doesn't know — Avatar falls back. */
  accent?: string | null;
}

export type ProfileVisibility = "everyone" | "friends" | "nobody";
export type StatsVisibility = "friends" | "nobody";

/** Mirrors profile_service.Preferences. */
export interface Preferences {
  theme: "system" | "light" | "dark";
  onboarded: boolean;
  currency_symbol: string;
  default_rules: {
    taidi?: GameRules;
    mahjong?: MahjongRules;
  };
}

/** Your own profile carries everything Settings edits, including the
 * address on file. */
export interface MyProfile extends UserProfile {
  email: string | null;
  bio: string | null;
  city: string | null;
  preferences: Preferences;
  profile_visibility: ProfileVisibility;
  stats_visibility: StatsVisibility;
  searchable: boolean;
}

export type Friendship = "self" | "friends" | "pending_out" | "pending_in" | "none";

/** Someone's profile page. bio and city are null when their privacy hides
 * them from you; stats is null unless it's you or a friend they allow. */
export interface PublicProfile extends UserProfile {
  bio: string | null;
  city: string | null;
  friendship: Friendship;
  stats: {
    total_sessions: number;
    total_cents: number;
    favorite_game: "taidi" | "mahjong" | "tied" | null;
    /** Positive for a run of winning sessions, negative for losing. */
    current_streak: number;
    last_played: string | null;
  } | null;
}

/** A friendship or pending request. `user` is always the other person. */
export interface FriendEdge {
  id: string;
  user: UserProfile;
  created_at: string;
}

export interface FriendsResponse {
  friends: FriendEdge[];
  incoming: FriendEdge[];
  outgoing: FriendEdge[];
}
