"use client";

import { getAccessToken, refreshAccessToken } from "./auth";
import { API_URL, API_URL_MISSING } from "./config";
import type { MahjongRules } from "./mahjongTypes";
import type { ActiveRoom, AnyRoomState, GameRules, GameType, TaidiRoomState } from "./types";

/** Long enough for a cold API on a bad table-side connection; short enough
 * that a dead request can't leave every button on the page disabled. */
const TIMEOUT_MS = 12_000;

/** A 409 carries {message, state} so the caller can resync without a refetch. */
export interface ConflictDetail {
  message: string;
  state: AnyRoomState;
}

export class ApiError extends Error {
  /** 0 when the request never got an HTTP answer (offline, timed out). */
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === "string"
        ? detail
        : ((detail as { message?: string })?.message ?? `Request failed (${status})`);
    super(message);
    this.status = status;
    this.detail = detail;
  }

  /** Which game's state a 409 carries is only known from its game_type, so
   * callers narrow it there rather than trusting the endpoint they hit. */
  get conflict(): ConflictDetail | null {
    // Not every 409 carries a state (e.g. "already in another room", or the
    // server running out of retries) — callers resync from it, so only
    // claim a conflict when there's something to resync to.
    const d = this.detail as Partial<ConflictDetail> | null;
    return this.status === 409 && d?.state ? (d as ConflictDetail) : null;
  }
}

async function send(path: string, options: RequestInit, token: string | null): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, {
      ...options,
      signal: options.signal ?? AbortSignal.timeout(TIMEOUT_MS),
      headers: {
        // A Blob body (a photo) carries its own type; everything else is JSON.
        "Content-Type": options.body instanceof Blob ? options.body.type : "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch (e) {
    const timedOut = e instanceof DOMException && e.name === "TimeoutError";
    throw new ApiError(
      0,
      timedOut ? "The server took too long to answer — try again." : "Can't reach the server.",
    );
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!API_URL) throw new ApiError(0, API_URL_MISSING);
  let res = await send(path, options, await getAccessToken());
  // A token can expire between being read and arriving. One refresh and
  // retry covers that; a second 401 is a real sign-in problem.
  if (res.status === 401) {
    const fresh = await refreshAccessToken();
    if (fresh) res = await send(path, options, fresh);
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      // no JSON body — keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

/** Raw bytes as the body — same auth, timeout and 401 retry as request(). */
export const upload = <T>(path: string, data: Blob, method: "PUT" | "POST" = "PUT") =>
  request<T>(path, { method, body: data });

type Room = TaidiRoomState;

/** The host entering a guest's turn sends as_player; omitted, a command is
 * the caller's own. */
export const actingAs = (asPlayer?: string) => (asPlayer ? { as_player: asPlayer } : {});

export const api = {
  /** Rules ride along from /new and are held as the room's draft_rules
   * until the host starts it. */
  createRoom: (gameType: GameType, rules?: GameRules | MahjongRules, groupId?: string | null) =>
    post<AnyRoomState>("/rooms", {
      game_type: gameType,
      ...(rules ? { rules } : {}),
      ...(groupId ? { group_id: groupId } : {}),
    }),
  byCode: (code: string) =>
    request<{ room_id: string; game_type: GameType }>(`/rooms/by-code/${code}`),
  activeRoom: () => request<ActiveRoom>("/rooms/active"),
  /** Either game — the state endpoint is shared. */
  getState: (roomId: string) => request<AnyRoomState>(`/rooms/${roomId}/state`),
  join: (roomId: string) => post<Room>(`/rooms/${roomId}/join`),
  leave: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/leave`, { expected_seq: expectedSeq }),
  disband: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/disband`, { expected_seq: expectedSeq }),
  /** No rules: the server starts on the room's draft_rules. */
  start: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/start`, { expected_seq: expectedSeq }),
  // Everything that acts on a round names it (round_no = the last round as
  // this device saw it). The server then refuses it if that round has
  // since closed, instead of applying a tap meant for round N to round N+1.
  claimWin: (roomId: string, expectedSeq: number, roundNo: number, asPlayer?: string) =>
    post<Room>(`/rooms/${roomId}/win`, {
      expected_seq: expectedSeq,
      round_no: roundNo,
      ...actingAs(asPlayer),
    }),
  submitCards: (
    roomId: string,
    expectedSeq: number,
    roundNo: number,
    cards: number,
    asPlayer?: string,
  ) =>
    post<Room>(`/rooms/${roomId}/cards`, {
      expected_seq: expectedSeq,
      round_no: roundNo,
      cards,
      ...actingAs(asPlayer),
    }),
  submitFor: (
    roomId: string,
    expectedSeq: number,
    roundNo: number,
    targetPlayer: string,
    cards: number,
  ) =>
    post<Room>(`/rooms/${roomId}/submit-for`, {
      expected_seq: expectedSeq,
      round_no: roundNo,
      target_player: targetPlayer,
      cards,
    }),
  specialHand: (roomId: string, expectedSeq: number, roundNo: number, asPlayer?: string) =>
    post<Room>(`/rooms/${roomId}/special`, {
      expected_seq: expectedSeq,
      round_no: roundNo,
      ...actingAs(asPlayer),
    }),
  stepOut: (roomId: string, expectedSeq: number, asPlayer?: string) =>
    post<Room>(`/rooms/${roomId}/step-out`, { expected_seq: expectedSeq, ...actingAs(asPlayer) }),
  voidSpecialHand: (roomId: string, expectedSeq: number, roundNo: number, asPlayer?: string) =>
    post<Room>(`/rooms/${roomId}/void-special`, {
      expected_seq: expectedSeq,
      round_no: roundNo,
      ...actingAs(asPlayer),
    }),
  voidLastRound: (roomId: string, expectedSeq: number, roundNo: number) =>
    post<Room>(`/rooms/${roomId}/void`, { expected_seq: expectedSeq, round_no: roundNo }),
  endGame: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/end`, { expected_seq: expectedSeq }),
};
