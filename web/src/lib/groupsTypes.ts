// Mirrors api/app/group_service.py's GroupSummary / GroupDetail
// .model_dump(mode="json"). Keep in sync by hand.

import type { UserProfile } from "./friendsTypes";
import type { GameType } from "./types";

export interface GroupSummary {
  group_id: string;
  name: string;
  member_count: number;
  games_played: number;
  last_played: string | null;
  is_owner: boolean;
}

export interface LeaderboardRow {
  player_id: string;
  display_name: string;
  /** Null for a guest nobody has claimed. */
  profile: UserProfile | null;
  sessions: number;
  net_cents: number;
  /** Sessions finished up. */
  wins: number;
}

export interface GroupGame {
  room_id: string;
  game_type: GameType;
  ended_at: string;
  /** [name, net cents], best first. */
  results: [string, number][];
}

export interface GroupDetail {
  group_id: string;
  name: string;
  owner_id: string;
  invite_code: string;
  members: UserProfile[];
  leaderboard: LeaderboardRow[];
  recent_games: GroupGame[];
}
