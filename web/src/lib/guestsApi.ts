"use client";

import { post, request } from "./api";
import type { AnyRoomState, GameType, RoomStatus } from "./types";

// Mirrors api/app/routers/guests.py and the guest endpoints in
// routers/rooms.py / routers/mahjong.py. Keep in sync by hand.

export interface GuestClaimLink {
  guest_id: string;
  display_name: string;
  claim_token: string;
  claimed: boolean;
}

/** What a claim link would claim — readable signed out. */
export interface ClaimPreview {
  display_name: string;
  game_type: GameType;
  status: RoomStatus;
  ended_at: string | null;
  net_cents: number;
  host_display_name: string | null;
  claimed: boolean;
}

// Same commands for both games, under each game's own router.
const base = (roomId: string, game: GameType) =>
  game === "mahjong" ? `/rooms/${roomId}/mahjong/guests` : `/rooms/${roomId}/guests`;

export const guestsApi = {
  add: <S extends AnyRoomState>(roomId: string, game: GameType, expectedSeq: number, name: string) =>
    post<S>(base(roomId, game), { expected_seq: expectedSeq, display_name: name }),
  remove: <S extends AnyRoomState>(
    roomId: string,
    game: GameType,
    expectedSeq: number,
    guestId: string,
  ) => post<S>(`${base(roomId, game)}/${guestId}/remove`, { expected_seq: expectedSeq }),
  /** Host only. */
  claimLinks: (roomId: string) =>
    request<{ guests: GuestClaimLink[] }>(`/rooms/${roomId}/guest-claims`),
  preview: (token: string) =>
    request<ClaimPreview>(`/guests/claim/${encodeURIComponent(token)}`),
  claim: (token: string) =>
    post<{ room_id: string; game_type: GameType }>(`/guests/claim/${encodeURIComponent(token)}`),
};

export const claimUrl = (token: string) => `${window.location.origin}/claim/${token}`;
