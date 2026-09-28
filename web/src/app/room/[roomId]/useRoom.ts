"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { readFreshState } from "@/lib/freshState";
import { usePolling } from "@/lib/usePolling";
import type { AnyRoomState } from "@/lib/types";

/** Why the room can't be shown. "offline" keeps the last state on screen;
 * the other two replace it (see RoomProblem). */
export type RoomProblemKind = "not-found" | "forbidden" | "offline";

function problemOf(e: Error | null): RoomProblemKind | null {
  if (!e) return null;
  if (e instanceof ApiError && e.status === 404) return "not-found";
  if (e instanceof ApiError && e.status === 403) return "forbidden";
  return "offline";
}

const isFatal = (e: Error) => {
  const p = problemOf(e);
  return p === "not-found" || p === "forbidden";
};

export interface RunOptions {
  /** The command names the round/hand it's for, so a 409 means that round
   * is over — retrying would apply the tap to the next one. Resync and say
   * so instead. */
  pinned?: boolean;
  /** Leave the result off-screen — for commands that navigate away (leave,
   * disband), where painting "you're no longer a member" would briefly
   * flash the join screen. */
  apply?: boolean;
}

/**
 * Everything the two room screens do identically: polling, the auto-join
 * from a shared link, the disbanded bounce, the command runner, the banner.
 * Only the game-specific table UI lives in TaidiRoom / MahjongRoom.
 */
export function useRoom<S extends AnyRoomState>({
  roomId,
  me,
  narrow,
  join,
  initial,
  onWrongGame,
  movedOn,
}: {
  roomId: string;
  me: string;
  /** Returns the state only if it's this game's — the one place a room of
   * the other game is caught before its fields are read. */
  narrow: (s: AnyRoomState) => S | null;
  join: (roomId: string) => Promise<S>;
  initial: AnyRoomState | null;
  /** Called with the state when the room turns out to be the other game. */
  onWrongGame: (actual: AnyRoomState) => void;
  /** Banner for a pinned command that arrived after its round/hand closed. */
  movedOn: string;
}) {
  const router = useRouter();
  const [banner, setBanner] = useState<string | null>(null);
  const [blockedBy, setBlockedBy] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // busy is state, so it only disables buttons after a re-render; two taps
  // inside one frame both see it false. The ref is what actually stops a
  // double-tap from charging someone twice.
  const inFlight = useRef(false);
  const joinedRef = useRef(false);
  // Computed once: re-reading sessionStorage and re-parsing it on every
  // render bought nothing but work.
  const [seed] = useState(() => initial ?? readFreshState<AnyRoomState>(roomId));

  const { data, error, setData } = usePolling<AnyRoomState>(() => api.getState(roomId), {
    intervalMs: 1500,
    deps: [roomId, me],
    initial: seed,
    isFatal,
  });

  const state = data ? narrow(data) : null;
  const wrongGame = data && !state ? data : null;
  const problem = problemOf(error);
  const isMember = !!(state && me in state.members);
  const isHost = state?.host_id === me;

  useEffect(() => {
    if (wrongGame) onWrongGame(wrongGame);
  }, [wrongGame, onWrongGame]);

  useEffect(() => {
    // The host disbanded the room while others were still in the lobby —
    // everyone still viewing it gets bounced home on their next poll.
    if (state?.status === "disbanded") router.replace("/");
  }, [state?.status, router]);

  // Auto-join once: if we landed here via a shared link/code without having
  // joined yet, and the room is still in its lobby, join automatically.
  useEffect(() => {
    if (!state || joinedRef.current) return;
    if (!isMember && state.status === "lobby") {
      joinedRef.current = true;
      join(roomId)
        .then(setData)
        .catch((e) => {
          setBanner(e instanceof ApiError ? e.message : "Couldn't join this room.");
          // Refused because you're already in another room: the API hands
          // back which one, so offer a way there instead of stranding you
          // on a lobby you can't enter.
          const other = (e instanceof ApiError ? e.detail : null) as {
            active_room_id?: string;
          } | null;
          if (other?.active_room_id) setBlockedBy(other.active_room_id);
        });
    }
  }, [state, isMember, roomId, join, setData]);

  /**
   * Runs one command against the state this device is showing.
   *
   * Unpinned commands (join, start, leave, end, ...) retry once on a 409:
   * someone else's event landing first doesn't invalidate them, so resync
   * and go again against the new seq. Pinned ones never retry — see
   * RunOptions.pinned.
   */
  async function run(
    action: (s: S) => Promise<S>,
    { pinned = false, apply = true }: RunOptions = {},
  ): Promise<S | null> {
    if (inFlight.current || !state) return null;
    inFlight.current = true;
    setBusy(true);
    setBanner(null);
    let current = state;
    try {
      for (let attempt = 0; ; attempt++) {
        try {
          const result = await action(current);
          if (apply) setData(result);
          return result;
        } catch (e) {
          const fresh = e instanceof ApiError && e.conflict ? narrow(e.conflict.state) : null;
          if (fresh) setData(fresh);
          if (fresh && pinned) {
            setBanner(movedOn);
          } else if (fresh && attempt === 0) {
            current = fresh;
            continue;
          } else {
            setBanner(
              fresh
                ? "Someone else keeps acting first — try again."
                : e instanceof ApiError
                  ? e.message
                  : "Something went wrong.",
            );
          }
          return null;
        }
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return {
    state,
    wrongGame,
    problem,
    isMember,
    isHost,
    busy,
    banner,
    blockedBy,
    run,
  };
}
