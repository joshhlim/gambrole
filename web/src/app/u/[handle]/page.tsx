"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { money } from "@/lib/format";
import { friendsApi } from "@/lib/friendsApi";
import type { Friendship, PublicProfile } from "@/lib/friendsTypes";
import { useCurrencySymbol } from "@/lib/preferences";
import { profileApi } from "@/lib/profileApi";
import Avatar from "@/components/Avatar";

const GAME_LABEL = { taidi: "Taidi", mahjong: "Mahjong", tied: "Both" } as const;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** "3 won" / "2 lost" — a run of sessions finished up or down. */
function streakText(n: number): string {
  if (n === 0) return "—";
  return `${Math.abs(n)} ${n > 0 ? "won" : "lost"}`;
}

function Tile({
  label,
  value,
  tone,
  testId,
}: {
  label: string;
  value: string;
  tone?: "pos" | "neg";
  testId?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2.5">
      <p className="mb-0.5 text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p
        data-testid={testId}
        className={`truncate text-base font-bold tabular ${
          tone === "pos" ? "text-brand-strong" : tone === "neg" ? "text-danger" : "text-foreground"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function ProfileSkeleton() {
  return (
    <div className="flex flex-col items-center gap-3" aria-busy="true" aria-label="Loading profile">
      <div className="h-24 w-24 animate-pulse rounded-full bg-border" />
      <div className="h-6 w-40 animate-pulse rounded bg-border" />
      <div className="h-4 w-24 animate-pulse rounded bg-border/70" />
      <div className="mt-4 h-11 w-full animate-pulse rounded-xl bg-border/60" />
    </div>
  );
}

/**
 * A player's profile: who they are, and — if they're you, or a friend who
 * allows it — how they've been doing. Anything their privacy hides arrives
 * as null and is simply left out.
 */
export default function ProfilePage() {
  const { handle } = useParams<{ handle: string }>();
  const router = useRouter();
  const { user, checked } = useStoredUser();
  useCurrencySymbol();
  const [profile, setProfile] = useState<PublicProfile | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    profileApi
      .get(decodeURIComponent(handle))
      .then((p) => !cancelled && setProfile(p))
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof ApiError ? e : new ApiError(0, "Couldn't load this profile."));
      });
    return () => {
      cancelled = true;
    };
  }, [user, handle]);

  async function befriend() {
    if (!profile) return;
    setBusy(true);
    setError(null);
    try {
      // Sending to someone who already asked you accepts theirs.
      const r = await friendsApi.sendRequest(profile.user_id);
      const friendship: Friendship = r.status === "accepted" ? "friends" : "pending_out";
      setProfile({ ...profile, friendship });
      // Being friends can open up their stats and details.
      if (friendship === "friends") setProfile(await profileApi.get(profile.user_id));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't go through.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;

  const stats = profile?.stats ?? null;
  const self = profile?.friendship === "self";

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-6 flex items-center gap-3">
        <button
          onClick={() => (window.history.length > 1 ? router.back() : router.push("/"))}
          data-testid="back-btn"
          aria-label="Back"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
      </div>

      {loadError ? (
        <p data-testid="profile-error" className="py-12 text-center text-sm text-muted">
          {loadError.status === 404 ? "No such player." : loadError.message}
        </p>
      ) : !profile ? (
        <ProfileSkeleton />
      ) : (
        <div className="space-y-6">
          <div className="flex flex-col items-center text-center">
            <Avatar name={profile.display_name} url={profile.avatar_url} accent={profile.accent} size={96} />
            <h1 data-testid="profile-name" className="mt-4 max-w-full truncate text-2xl font-extrabold text-brand">
              {profile.display_name}
            </h1>
            {profile.username && (
              <p data-testid="profile-username" className="text-sm text-muted">
                @{profile.username}
              </p>
            )}
            {profile.city && (
              <p data-testid="profile-city" className="mt-1 flex items-center gap-1 text-sm text-muted">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path
                    d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                  <circle cx="12" cy="10" r="2.2" stroke="currentColor" strokeWidth="1.8" />
                </svg>
                {profile.city}
              </p>
            )}
            {profile.bio && (
              <p
                data-testid="profile-bio"
                className="mt-3 max-w-xs whitespace-pre-line break-words text-sm leading-relaxed text-foreground"
              >
                {profile.bio}
              </p>
            )}
          </div>

          <FriendAction
            friendship={profile.friendship}
            busy={busy}
            onBefriend={befriend}
            onEdit={() => router.push("/settings")}
          />
          {error && (
            <p data-testid="profile-action-error" className="text-center text-sm text-danger">
              {error}
            </p>
          )}

          {stats && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <Tile label="Games" value={String(stats.total_sessions)} testId="profile-stat-games" />
                <Tile
                  label="Net"
                  value={stats.total_cents > 0 ? `+${money(stats.total_cents)}` : money(stats.total_cents)}
                  tone={stats.total_cents < 0 ? "neg" : stats.total_cents > 0 ? "pos" : undefined}
                  testId="profile-stat-net"
                />
                <Tile
                  label="Favourite"
                  value={stats.favorite_game ? GAME_LABEL[stats.favorite_game] : "—"}
                />
                <Tile
                  label="Streak"
                  value={streakText(stats.current_streak)}
                  tone={stats.current_streak > 0 ? "pos" : stats.current_streak < 0 ? "neg" : undefined}
                />
              </div>
              {stats.last_played && (
                <p className="text-center text-xs text-muted">Last played {formatDate(stats.last_played)}</p>
              )}
              {stats.total_sessions > 0 && (
                <Link
                  href={self ? "/stats" : `/stats?player=${profile.user_id}`}
                  data-testid="profile-full-stats"
                  className="flex min-h-11 items-center justify-center rounded-xl border border-border bg-surface text-sm font-semibold text-brand"
                >
                  {self ? "My stats" : "Full stats"}
                </Link>
              )}
            </div>
          )}
        </div>
      )}
    </main>
  );
}

function FriendAction({
  friendship,
  busy,
  onBefriend,
  onEdit,
}: {
  friendship: Friendship;
  busy: boolean;
  onBefriend: () => void;
  onEdit: () => void;
}) {
  const quiet =
    "flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border border-border bg-surface text-sm font-semibold";
  const primary =
    "min-h-11 w-full rounded-xl bg-primary text-sm font-semibold text-on-primary disabled:opacity-50";
  switch (friendship) {
    case "self":
      return (
        <button type="button" onClick={onEdit} data-testid="profile-edit-btn" className={`${quiet} text-brand`}>
          Edit profile
        </button>
      );
    case "friends":
      return (
        <p data-testid="profile-friend-state" className={`${quiet} text-brand-strong`}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="m5 12.5 4.5 4.5L19 7.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Friends
        </p>
      );
    case "pending_out":
      return (
        <p data-testid="profile-friend-state" className={`${quiet} text-muted`}>
          Requested
        </p>
      );
    case "pending_in":
      return (
        <button type="button" onClick={onBefriend} disabled={busy} data-testid="profile-accept-btn" className={primary}>
          Accept friend request
        </button>
      );
    default:
      return (
        <button type="button" onClick={onBefriend} disabled={busy} data-testid="profile-add-btn" className={primary}>
          Add friend
        </button>
      );
  }
}
