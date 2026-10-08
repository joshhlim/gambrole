"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { money } from "@/lib/format";
import { useCurrencySymbol } from "@/lib/preferences";
import { profileHref } from "@/lib/profileApi";
import { groupJoinUrl, groupsApi } from "@/lib/groupsApi";
import type { GroupDetail } from "@/lib/groupsTypes";
import Avatar from "@/components/Avatar";
import { ConfirmAction } from "@/components/ConfirmAction";
import GuestTag from "@/components/GuestTag";
import ShareLink from "@/components/ShareLink";
import TabBar from "@/components/TabBar";
import TabTransition from "@/components/TabTransition";
import { RowsSkeleton } from "@/components/Skeleton";

const TABS = ["leaderboard", "games", "members"] as const;
type Tab = (typeof TABS)[number];

const GAME_LABEL = { taidi: "Taidi", mahjong: "Mahjong" } as const;

const quietBtn =
  "w-full rounded-xl border border-border py-2.5 text-xs font-semibold text-muted disabled:opacity-50";
const sectionLabel = "mb-2 text-xs uppercase tracking-widest text-muted";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const signed = (cents: number) => (cents > 0 ? `+${money(cents)}` : money(cents));

export default function GroupPage() {
  const { groupId } = useParams<{ groupId: string }>();
  const router = useRouter();
  const { user, checked } = useStoredUser();
  useCurrencySymbol();
  const [group, setGroup] = useState<GroupDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<Tab>("leaderboard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    groupsApi
      .get(groupId)
      .then((g) => !cancelled && setGroup(g))
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof ApiError ? e : new ApiError(0, "Couldn't load this group."));
      });
    return () => {
      cancelled = true;
    };
  }, [user, groupId]);

  /** Every owner action answers with the updated group (or, for leave and
   * delete, nothing left to show — `then` navigates away instead). */
  async function act<T>(fn: () => Promise<T>, then?: (r: T) => void) {
    setBusy(true);
    setError(null);
    try {
      const r = await fn();
      if (then) then(r);
      else setGroup(r as GroupDetail);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't go through.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;

  const isOwner = group?.owner_id === user.user_id;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-6 flex items-center gap-3">
        <button
          onClick={() => router.push("/groups")}
          data-testid="back-btn"
          aria-label="Back"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        {group && (
          <div className="min-w-0">
            <h1 data-testid="group-title" className="truncate text-lg font-extrabold text-brand">
              {group.name}
            </h1>
            <p className="text-xs text-muted">
              {group.members.length} member{group.members.length === 1 ? "" : "s"}
            </p>
          </div>
        )}
      </div>

      {loadError ? (
        <p data-testid="group-error" className="py-8 text-center text-sm text-muted">
          {loadError.status === 404
            ? "Group not found."
            : loadError.status === 403
              ? "You're not in this group."
              : loadError.message}
        </p>
      ) : !group ? (
        <RowsSkeleton rows={4} />
      ) : (
        <div className="space-y-5">
          <button
            onClick={() => router.push(`/new?group=${group.group_id}`)}
            data-testid="group-new-game-btn"
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary"
          >
            New game
          </button>

          {error && (
            <p data-testid="group-action-error" className="text-center text-sm text-danger">
              {error}
            </p>
          )}

          <TabBar
            tabs={TABS}
            active={tab}
            onSelect={setTab}
            testIdPrefix="group-tab"
          />

          <TabTransition tabKey={tab} order={TABS}>
            {tab === "leaderboard" && <Leaderboard group={group} />}
            {tab === "games" && (
              <RecentGames group={group} onOpen={(id, g) => router.push(`/room/${id}?g=${g}`)} />
            )}
            {tab === "members" && (
              <div className="space-y-6">
                <Invite
                  group={group}
                  isOwner={isOwner}
                  busy={busy}
                  onRotate={() => act(() => groupsApi.rotateCode(group.group_id))}
                />
                <Members
                  group={group}
                  me={user.user_id}
                  isOwner={isOwner}
                  busy={busy}
                  onRemove={(id) => act(() => groupsApi.removeMember(group.group_id, id))}
                />
                {isOwner && (
                  <Settings
                    group={group}
                    busy={busy}
                    onRename={(name) => act(() => groupsApi.rename(group.group_id, name))}
                    onDelete={() =>
                      act(
                        () => groupsApi.remove(group.group_id),
                        () => router.push("/groups"),
                      )
                    }
                  />
                )}
                <ConfirmAction
                  label="Leave group"
                  prompt={
                    isOwner && group.members.length > 1
                      ? "Leave? Ownership passes to the longest-standing member."
                      : group.members.length === 1
                        ? "Leave? You're the last member, so the group is deleted."
                        : "Leave this group?"
                  }
                  confirmLabel="Leave"
                  testIds={{ open: "leave-group-btn", confirm: "confirm-leave-group-btn", cancel: "cancel-leave-group-btn" }}
                  busy={busy}
                  onConfirm={() =>
                    act(
                      () => groupsApi.leave(group.group_id),
                      () => router.push("/groups"),
                    )
                  }
                  buttonClassName={quietBtn}
                />
              </div>
            )}
          </TabTransition>
        </div>
      )}
    </main>
  );
}

function Leaderboard({ group }: { group: GroupDetail }) {
  if (group.leaderboard.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">No games yet.</p>;
  }
  return (
    <div className="space-y-2">
      {group.leaderboard.map((row, idx) => {
        const cls = `flex items-center gap-3 rounded-xl border px-3 py-2.5 ${
          idx === 0 ? "border-gold bg-highlight" : "border-border bg-surface"
        }`;
        const body = (
          <>
            <span className="w-5 shrink-0 text-center text-xs font-bold text-muted tabular">{idx + 1}</span>
            <Avatar name={row.display_name} url={row.profile?.avatar_url} accent={row.profile?.accent} size={32} />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className="min-w-0 truncate">{row.display_name}</span>
                {!row.profile && <GuestTag />}
              </p>
              <p className="text-xs text-muted">
                {row.sessions} game{row.sessions === 1 ? "" : "s"} · {row.wins} win{row.wins === 1 ? "" : "s"}
              </p>
            </div>
            <span
              data-testid="leaderboard-net"
              className={`shrink-0 text-sm font-bold tabular ${row.net_cents < 0 ? "text-danger" : "text-brand-strong"}`}
            >
              {money(row.net_cents)}
            </span>
          </>
        );
        // An account opens its profile; a guest has none to open.
        return row.profile ? (
          <Link
            key={row.player_id}
            href={profileHref(row.profile)}
            data-testid="leaderboard-row"
            data-player={row.display_name}
            className={cls}
          >
            {body}
          </Link>
        ) : (
          <div key={row.player_id} data-testid="leaderboard-row" data-player={row.display_name} className={cls}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

function RecentGames({
  group,
  onOpen,
}: {
  group: GroupDetail;
  onOpen: (roomId: string, game: GroupDetail["recent_games"][number]["game_type"]) => void;
}) {
  if (group.recent_games.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">No games yet.</p>;
  }
  return (
    <div className="space-y-2">
      {group.recent_games.map((g) => (
        <button
          key={g.room_id}
          onClick={() => onOpen(g.room_id, g.game_type)}
          data-testid="group-game-row"
          className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-left"
        >
          <p className="text-sm font-semibold text-foreground">
            {GAME_LABEL[g.game_type]}
            <span className="font-normal text-muted"> · {formatDate(g.ended_at)}</span>
          </p>
          <p className="truncate text-xs text-muted tabular">
            {g.results
              .slice(0, 3)
              .map(([name, cents]) => `${name} ${signed(cents)}`)
              .join(" · ")}
            {g.results.length > 3 ? " · …" : ""}
          </p>
        </button>
      ))}
    </div>
  );
}

function Invite({
  group,
  isOwner,
  busy,
  onRotate,
}: {
  group: GroupDetail;
  isOwner: boolean;
  busy: boolean;
  onRotate: () => void;
}) {
  return (
    <div>
      <p className={sectionLabel}>Invite</p>
      <div className="space-y-3 rounded-xl border border-border bg-surface px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <p
            data-testid="group-invite-code"
            className="min-w-0 truncate text-xl font-extrabold tracking-[0.2em] text-brand"
          >
            {group.invite_code}
          </p>
          <ShareLink
            url={groupJoinUrl(group.invite_code)}
            title={group.name}
            label="Share link"
            testId="group-share-btn"
            className="shrink-0 rounded-lg border border-brand-strong px-3 py-1.5 text-xs font-semibold text-brand"
          />
        </div>
        {isOwner && (
          <ConfirmAction
            label="New code"
            prompt="Make a new code? The current link stops working."
            confirmLabel="New code"
            testIds={{ open: "rotate-code-btn", confirm: "confirm-rotate-code-btn", cancel: "cancel-rotate-code-btn" }}
            busy={busy}
            onConfirm={onRotate}
            buttonClassName="w-full rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
          />
        )}
      </div>
    </div>
  );
}

function Members({
  group,
  me,
  isOwner,
  busy,
  onRemove,
}: {
  group: GroupDetail;
  me: string;
  isOwner: boolean;
  busy: boolean;
  onRemove: (userId: string) => void;
}) {
  // One row at a time asks "remove?" — inline, under that row.
  const [removing, setRemoving] = useState<string | null>(null);
  return (
    <div>
      <p className={sectionLabel}>Members</p>
      <div className="space-y-2">
        {group.members.map((m) => (
          <div
            key={m.user_id}
            data-testid="group-member"
            data-player={m.display_name}
            className="rounded-xl border border-border bg-surface px-3 py-2.5"
          >
            <div className="flex items-center gap-3">
              <Link
                href={profileHref(m)}
                data-testid="group-member-link"
                className="flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-lg"
              >
                <Avatar name={m.display_name} url={m.avatar_url} accent={m.accent} size={36} />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <span className="min-w-0 truncate">{m.display_name}</span>
                    {m.user_id === group.owner_id && (
                      <span className="shrink-0 text-xs font-semibold text-gold-text">OWNER</span>
                    )}
                  </p>
                  {m.username && <p className="truncate text-xs text-muted">@{m.username}</p>}
                </div>
              </Link>
              {isOwner && m.user_id !== me && removing !== m.user_id && (
                <button
                  type="button"
                  onClick={() => setRemoving(m.user_id)}
                  disabled={busy}
                  data-testid="remove-member-btn"
                  className="min-h-11 shrink-0 px-2 text-xs font-semibold text-muted disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
            {removing === m.user_id && (
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setRemoving(null);
                    onRemove(m.user_id);
                  }}
                  disabled={busy}
                  data-testid="confirm-remove-member-btn"
                  className="flex-1 rounded-lg bg-danger-fill py-2 text-xs font-semibold text-on-primary disabled:opacity-50"
                >
                  Remove
                </button>
                <button
                  type="button"
                  onClick={() => setRemoving(null)}
                  data-testid="cancel-remove-member-btn"
                  className="flex-1 rounded-lg border border-border py-2 text-xs font-semibold text-muted"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Settings({
  group,
  busy,
  onRename,
  onDelete,
}: {
  group: GroupDetail;
  busy: boolean;
  onRename: (name: string) => void;
  onDelete: () => void;
}) {
  const [name, setName] = useState(group.name);
  const trimmed = name.trim();
  return (
    <div>
      <p className={sectionLabel}>Settings</p>
      <div className="space-y-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (trimmed && trimmed !== group.name) onRename(trimmed);
          }}
          className="flex gap-2"
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            aria-label="Group name"
            data-testid="rename-group-input"
            className="min-w-0 flex-1 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm outline-none focus:border-brand-strong"
          />
          <button
            type="submit"
            disabled={busy || !trimmed || trimmed === group.name}
            data-testid="rename-group-btn"
            className="shrink-0 rounded-xl border border-brand-strong px-4 text-sm font-semibold text-brand disabled:opacity-50"
          >
            Rename
          </button>
        </form>
        <ConfirmAction
          label="Delete group"
          prompt="Delete this group for everyone?"
          confirmLabel="Delete"
          testIds={{ open: "delete-group-btn", confirm: "confirm-delete-group-btn", cancel: "cancel-delete-group-btn" }}
          busy={busy}
          onConfirm={onDelete}
          buttonClassName={quietBtn}
        />
      </div>
    </div>
  );
}
