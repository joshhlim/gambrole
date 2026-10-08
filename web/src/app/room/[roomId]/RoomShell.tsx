"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { groupsApi } from "@/lib/groupsApi";
import type { UserProfile } from "@/lib/friendsTypes";
import { profileHref } from "@/lib/profileApi";
import { useProfiles } from "@/lib/useProfiles";
import type { AnyRoomState } from "@/lib/types";
import Avatar from "@/components/Avatar";
import type { RoomProblemKind } from "./useRoom";

/** Full-screen stand-in for a room that can't be shown at all. */
export function RoomProblem({ kind }: { kind: Exclude<RoomProblemKind, "offline"> }) {
  const router = useRouter();
  return (
    <main className="flex flex-1 items-center justify-center px-5 py-8">
      <div className="w-full max-w-sm space-y-4 text-center">
        <p data-testid="room-problem" className="text-sm text-muted">
          {kind === "not-found" ? "Room not found." : "You're not in this game."}
        </p>
        <button
          onClick={() => router.push("/")}
          data-testid="room-problem-home-btn"
          className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary"
        >
          Home
        </button>
      </div>
    </main>
  );
}

export function RoomLoading({ offline }: { offline?: boolean }) {
  return (
    <main className="flex flex-1 items-center justify-center text-sm text-muted">
      {offline ? "Reconnecting…" : "Loading…"}
    </main>
  );
}

// Group names by id, for the room header. A room's group never changes, so
// one lookup per group per page load is plenty — polling must not refetch.
const groupNames = new Map<string, string | null>();

/** The name of the group a room belongs to, or null when you aren't in it
 * (a friend-of-a-friend at the table) — then there's just no label. */
function useGroupName(groupId: string | null | undefined): string | null {
  const [name, setName] = useState<{ id: string; name: string | null } | null>(null);
  useEffect(() => {
    if (!groupId || groupNames.has(groupId)) return;
    let cancelled = false;
    // The list rather than the group itself: it's what a non-member can ask
    // for without a 403, and it skips the leaderboard query.
    groupsApi
      .list()
      .then(({ groups }) => {
        for (const g of groups) groupNames.set(g.group_id, g.name);
        if (!groupNames.has(groupId)) groupNames.set(groupId, null);
        if (!cancelled) setName({ id: groupId, name: groupNames.get(groupId) ?? null });
      })
      .catch(() => {
        /* a missing label isn't worth an error */
      });
    return () => {
      cancelled = true;
    };
  }, [groupId]);
  if (!groupId) return null;
  if (groupNames.has(groupId)) return groupNames.get(groupId) ?? null;
  return name?.id === groupId ? name.name : null;
}

/**
 * The frame both room screens share: a back arrow that only ever
 * minimises (you stay in the room; home's "Rejoin Room" is the way back),
 * a quiet reconnecting marker, and the banner for refused actions.
 *
 * The back arrow is never disabled — a request stuck in flight must not
 * trap anyone on the page.
 */
export function RoomFrame({
  offline,
  banner,
  blockedBy,
  groupId,
  children,
}: {
  offline: boolean;
  banner: string | null;
  blockedBy: string | null;
  groupId?: string | null;
  children: ReactNode;
}) {
  const router = useRouter();
  const [going, setGoing] = useState(false);
  const groupName = useGroupName(groupId);

  // The refusal only names the other room, not its game — ask which one it
  // is, so the link lands on the right screen without a lookup detour.
  async function goToActive() {
    if (!blockedBy || going) return;
    setGoing(true);
    const active = await api.activeRoom().catch(() => null);
    const g = active?.room_id === blockedBy ? active.game_type : undefined;
    router.push(`/room/${blockedBy}${g ? `?g=${g}` : ""}`);
  }

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center justify-between gap-3 mb-6">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          aria-label="Back"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        {groupName && (
          <Link
            href={`/groups/${groupId}`}
            data-testid="room-group-name"
            className="min-w-0 flex-1 truncate text-center text-xs font-semibold uppercase tracking-widest text-muted"
          >
            {groupName}
          </Link>
        )}
        {offline && (
          <span
            data-testid="reconnecting"
            role="status"
            className="rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-muted"
          >
            Reconnecting…
          </span>
        )}
        {/* Balances the back arrow so the group name sits centred. */}
        {groupName && !offline && <span aria-hidden className="w-11 shrink-0" />}
      </div>

      {banner && (
        <div
          data-testid="room-banner"
          role="status"
          className="mb-4 rounded-lg border border-border bg-surface px-4 py-2 text-sm text-muted"
        >
          {banner}
          {blockedBy && (
            <button
              onClick={goToActive}
              disabled={going}
              data-testid="go-to-active-room-btn"
              className="mt-2 w-full rounded-lg bg-primary-strong py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
            >
              Go to your game
            </button>
          )}
        </div>
      )}

      {children}
    </main>
  );
}

/** One line of the room's rules, for settling "wait, what are we playing
 * for?" without leaving the table. */
export function RulesLine({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p data-testid="rules-summary" className="text-center text-[11px] text-muted">
      {text}
    </p>
  );
}

/**
 * Photos and accents for everyone with an account at this table, current
 * or departed. Fetched once per player per page load (see useProfiles) —
 * never per poll.
 */
export function useRoomProfiles(state: AnyRoomState | null): Record<string, UserProfile> {
  const ids = state
    ? [...Object.keys(state.members), ...Object.keys(state.balances)].filter(
        (id) => !state.members[id]?.is_guest,
      )
    : [];
  return useProfiles(ids);
}

/** Avatar and name, in a row. `link` makes it open their profile — used
 * where a tap can't be mistaken for a game action (lobby, final results). */
export function PlayerLabel({
  playerId,
  name,
  profile,
  link = false,
  size = 28,
}: {
  playerId: string;
  name: string;
  profile?: UserProfile;
  link?: boolean;
  size?: number;
}) {
  const inner = (
    <>
      <Avatar name={name} url={profile?.avatar_url} accent={profile?.accent} size={size} />
      <span className="min-w-0 truncate font-medium">{name}</span>
    </>
  );
  if (link && profile) {
    return (
      <Link
        href={profileHref({ user_id: playerId, username: profile.username })}
        data-testid="player-profile-link"
        className="flex min-w-0 items-center gap-2.5"
      >
        {inner}
      </Link>
    );
  }
  return <span className="flex min-w-0 items-center gap-2.5">{inner}</span>;
}

// Shared well beyond the room screens now (debts, groups); re-exported so
// the room code keeps importing it from here.
export { ConfirmAction } from "@/components/ConfirmAction";
