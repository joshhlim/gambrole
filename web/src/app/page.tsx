"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useStoredUser, type CurrentUser } from "@/lib/auth";
import { debtsApi } from "@/lib/debtsApi";
import type { DebtsResponse } from "@/lib/debtsTypes";
import { money } from "@/lib/format";
import { groupHref, roomHref } from "@/lib/routes";
import { groupsApi } from "@/lib/groupsApi";
import type { GroupSummary } from "@/lib/groupsTypes";
import { historyApi } from "@/lib/historyApi";
import type { HistoryEntry } from "@/lib/historyTypes";
import { useCurrencySymbol } from "@/lib/preferences";
import type { ActiveRoom } from "@/lib/types";
import SignInPanel from "@/components/SignInPanel";

const GAME_LABEL = { taidi: "Taidi", mahjong: "Mahjong" } as const;

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Late night" : h < 12 ? "Morning" : h < 18 ? "Afternoon" : "Evening";
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

const signed = (cents: number) => (cents > 0 ? `+${money(cents)}` : money(cents));

/** Everything the dashboard shows, tagged with whose it is: a different
 * account signing in on this phone must never see the last one's while
 * its own loads. Each part is null until it arrives, and stays null if its
 * request fails — a missing card shouldn't take the page down. */
interface Dashboard {
  userId: string;
  active: ActiveRoom | null;
  debts: DebtsResponse | null;
  games: HistoryEntry[] | null;
  groups: GroupSummary[] | null;
}

function useDashboard(user: CurrentUser | null): Dashboard | null {
  const [data, setData] = useState<Dashboard | null>(null);
  useEffect(() => {
    if (!user) return;
    const userId = user.user_id;
    let cancelled = false;
    const put = (patch: Partial<Dashboard>) =>
      !cancelled &&
      setData((d) => ({
        ...(d && d.userId === userId ? d : { userId, active: null, debts: null, games: null, groups: null }),
        ...patch,
      }));
    // The way back into a live game from a device that never saw its URL —
    // e.g. picking up on a laptop after the phone died mid-game.
    api.activeRoom().then((active) => put({ active }), () => {});
    debtsApi.getMine().then((debts) => put({ debts }), () => {});
    historyApi.getMine().then((h) => put({ games: h.games }), () => {});
    groupsApi.list().then((g) => put({ groups: g.groups }), () => {});
    return () => {
      cancelled = true;
    };
  }, [user]);
  return data && user && data.userId === user.user_id ? data : null;
}

function Hero() {
  return (
    <div className="mb-10 text-center">
      <div className="mx-auto mb-4 flex h-16 w-16 rotate-3 items-center justify-center rounded-2xl bg-tile shadow-lg shadow-black/15">
        <span className="font-display text-3xl font-extrabold text-gold-bright">G</span>
      </div>
      <h1 className="text-3xl font-extrabold tracking-tight text-brand">
        Gam<span className="text-gold">BRO</span>le
      </h1>
      <p className="mt-1.5 text-[10px] uppercase tracking-[0.25em] text-muted">Game night, settled</p>
    </div>
  );
}

const card = "rounded-2xl border border-border bg-surface";
const sectionHead = "mb-2 flex items-baseline justify-between";
const sectionLabel = "text-xs font-semibold uppercase tracking-widest text-muted";
const seeAll = "min-h-8 px-1 text-xs font-semibold text-brand";

export default function HomePage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  useCurrencySymbol();
  const data = useDashboard(user);
  // Signup can succeed while claiming the username fails; the form that
  // knows is gone by then (it unmounts on sign-in), so it reports here.
  const [notice, setNotice] = useState<{ userId: string; text: string } | null>(null);

  if (!checked) return null;

  if (!user) {
    return (
      <main className="flex flex-1 flex-col px-6 py-6">
        <div className="flex w-full flex-1 items-center justify-center">
          <div className="w-full max-w-sm">
            <Hero />
            <SignInPanel onSignedIn={(u, text) => text && setNotice({ userId: u.user_id, text })} />
          </div>
        </div>
      </main>
    );
  }

  const active = data?.active?.room_id ? data.active : null;
  const open = (d: { status: string }) => d.status !== "approved";
  const youOwe = data?.debts?.owing.filter(open).reduce((t, d) => t + d.amount_cents, 0) ?? 0;
  const owedToYou = data?.debts?.owed.filter(open).reduce((t, d) => t + d.amount_cents, 0) ?? 0;
  const toApprove = data?.debts?.owed.filter((d) => d.status === "marked_paid").length ?? 0;
  const games = data?.games?.slice(0, 3) ?? null;
  const groups = data?.groups ?? null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 space-y-6 px-5 py-4">
      <div>
        <p className="text-sm text-muted">{greeting()},</p>
        <h1 className="truncate font-display text-3xl font-extrabold tracking-tight text-brand">
          {user.display_name}
        </h1>
      </div>

      {notice && notice.userId === user.user_id && (
        <p data-testid="signin-notice" className="text-center text-sm text-muted">
          {notice.text}
        </p>
      )}

      {active && (
        <button
          onClick={() => active.room_id && router.push(roomHref(active.room_id, active.game_type))}
          data-testid="rejoin-room-btn"
          className="w-full rounded-2xl bg-primary-strong p-5 text-left text-on-primary shadow-lg shadow-black/15 active:scale-[0.99]"
        >
          <span className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest opacity-80">
            <span className="h-2 w-2 animate-pulse rounded-full bg-gold-bright" />
            {active.status === "lobby" ? "Waiting to start" : "Game in progress"}
          </span>
          <span className="block font-display text-2xl font-extrabold">
            {active.game_type ? GAME_LABEL[active.game_type] : "Your game"} · {active.invite_code}
          </span>
          <span className="mt-1 block text-sm opacity-90">Tap to rejoin the table →</span>
        </button>
      )}

      <button
        onClick={() => router.push("/play")}
        data-testid="play-btn"
        className={
          active
            ? `${card} w-full p-4 text-left text-sm font-semibold text-brand active:bg-background`
            : "w-full rounded-2xl bg-primary p-5 text-left text-on-primary shadow-lg shadow-black/15 active:scale-[0.99]"
        }
      >
        {active ? (
          "Start or join another game"
        ) : (
          <>
            <span className="block font-display text-2xl font-extrabold">Start a game</span>
            <span className="mt-0.5 block text-sm opacity-90">Taidi or Mahjong, scores kept for you</span>
          </>
        )}
      </button>

      <section>
        <div className={sectionHead}>
          <h2 className={sectionLabel}>Balance</h2>
          <button onClick={() => router.push("/debts")} className={seeAll} data-testid="home-debts-link">
            Debts →
          </button>
        </div>
        <button
          onClick={() => router.push("/debts")}
          className={`${card} grid w-full grid-cols-2 divide-x divide-border text-left active:bg-background`}
        >
          <span className="p-4">
            <span className="block text-xs text-muted">You&apos;re owed</span>
            <span
              data-testid="home-owed"
              className={`block truncate text-xl font-bold tabular ${owedToYou > 0 ? "text-brand-strong" : "text-foreground"}`}
            >
              {data?.debts ? money(owedToYou) : "—"}
            </span>
          </span>
          <span className="p-4">
            <span className="block text-xs text-muted">You owe</span>
            <span
              data-testid="home-owing"
              className={`block truncate text-xl font-bold tabular ${youOwe > 0 ? "text-danger" : "text-foreground"}`}
            >
              {data?.debts ? money(youOwe) : "—"}
            </span>
          </span>
        </button>
        {toApprove > 0 && (
          <p className="mt-2 text-xs text-muted">
            {toApprove} {toApprove === 1 ? "payment needs" : "payments need"} your OK.
          </p>
        )}
      </section>

      <section>
        <div className={sectionHead}>
          <h2 className={sectionLabel}>Recent games</h2>
          <button onClick={() => router.push("/history")} className={seeAll}>
            All →
          </button>
        </div>
        {games === null ? (
          <div className={`${card} h-40 animate-pulse`} aria-busy="true" aria-label="Loading" />
        ) : games.length === 0 ? (
          <p className={`${card} p-4 text-sm text-muted`}>
            No games yet. Your results land here once your first game ends.
          </p>
        ) : (
          <div className={`${card} divide-y divide-border overflow-hidden`}>
            {games.map((g) => (
              <button
                key={g.room_id}
                onClick={() => router.push(roomHref(g.room_id, g.game_type))}
                data-testid="home-recent-game"
                className="flex min-h-14 w-full items-center justify-between px-4 text-left active:bg-background"
              >
                <span>
                  <span className="block text-sm font-semibold text-foreground">{GAME_LABEL[g.game_type]}</span>
                  <span className="block text-xs text-muted">{shortDate(g.ended_at)}</span>
                </span>
                <span
                  className={`text-base font-bold tabular ${
                    g.net_cents > 0 ? "text-brand-strong" : g.net_cents < 0 ? "text-danger" : "text-muted"
                  }`}
                >
                  {signed(g.net_cents)}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section>
        <div className={sectionHead}>
          <h2 className={sectionLabel}>Groups</h2>
          <button onClick={() => router.push("/groups")} className={seeAll} data-testid="groups-btn">
            {groups?.length ? "All →" : "Make one →"}
          </button>
        </div>
        {groups === null ? (
          <div className={`${card} h-16 animate-pulse`} aria-busy="true" aria-label="Loading" />
        ) : groups.length === 0 ? (
          <p className={`${card} p-4 text-sm text-muted`}>
            Play with the same crew? A group keeps a running leaderboard.
          </p>
        ) : (
          <div className="-mx-5 flex gap-3 overflow-x-auto px-5 pb-1">
            {groups.map((g) => (
              <button
                key={g.group_id}
                onClick={() => router.push(groupHref(g.group_id))}
                className={`${card} w-40 shrink-0 p-4 text-left active:bg-background`}
              >
                <span className="block truncate text-sm font-semibold text-foreground">{g.name}</span>
                <span className="block text-xs text-muted">
                  {g.member_count} {g.member_count === 1 ? "member" : "members"} · {g.games_played}{" "}
                  {g.games_played === 1 ? "game" : "games"}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
