"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { friendsApi } from "@/lib/friendsApi";
import type { FriendsResponse, MyProfile, UserProfile } from "@/lib/friendsTypes";

type Tab = "friends" | "requests" | "add";

function handle(u: UserProfile): string | null {
  return u.username ? `@${u.username}` : null;
}

function PersonRow({
  user,
  sub,
  children,
  testId,
}: {
  user: UserProfile;
  sub?: string;
  children?: React.ReactNode;
  testId?: string;
}) {
  return (
    <div
      data-testid={testId}
      className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-foreground">{user.display_name}</p>
        <p className="truncate text-xs text-muted">{sub ?? handle(user) ?? "no username yet"}</p>
      </div>
      <div className="flex shrink-0 gap-1.5">{children}</div>
    </div>
  );
}

const btnPrimary =
  "rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50";
const btnGhost =
  "rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-muted disabled:opacity-50";

export default function FriendsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [tab, setTab] = useState<Tab>("friends");
  const [data, setData] = useState<FriendsResponse | null>(null);
  const [suggestions, setSuggestions] = useState<UserProfile[]>([]);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<UserProfile[] | null>(null);
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  const refresh = useCallback(async () => {
    const [list, sugg] = await Promise.all([friendsApi.list(), friendsApi.suggestions()]);
    setData(list);
    setSuggestions(sugg.results);
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    Promise.all([friendsApi.me(), friendsApi.list(), friendsApi.suggestions()])
      .then(([mine, list, sugg]) => {
        if (cancelled) return;
        setProfile(mine);
        setData(list);
        setSuggestions(sugg.results);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof ApiError ? e.message : "Couldn't load your friends.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function act(key: string, fn: () => Promise<unknown>, after?: string) {
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      await fn();
      await refresh();
      // A search result that's now a friend shouldn't keep offering "Add".
      if (results) setResults(results.filter((r) => r.user_id !== key));
      if (after) setNote(after);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't go through.");
    } finally {
      setBusy(null);
    }
  }

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setBusy("search");
    setError(null);
    setNote(null);
    try {
      setResults((await friendsApi.search(q)).results);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Search failed.");
    } finally {
      setBusy(null);
    }
  }

  if (!user) return null;
  const incoming = data?.incoming.length ?? 0;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-5 flex items-center gap-3">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Friends</h1>
      </div>

      {error && (
        <p data-testid="friends-error" className="mb-3 text-center text-sm text-danger">
          {error}
        </p>
      )}
      {note && (
        <p data-testid="friends-note" className="mb-3 text-center text-sm text-brand-strong">
          {note}
        </p>
      )}

      {/* Read-only: handles are chosen at sign-up and changed in Settings,
          so this screen just tells you what yours is. */}
      {profile?.username && (
        <div className="mb-4 flex items-center justify-between rounded-xl border border-border bg-surface px-3 py-2.5">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted">Friends find you as</p>
            <p data-testid="my-username" className="text-sm font-semibold text-brand">
              @{profile.username}
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.push("/settings")}
            data-testid="username-change-link"
            className={btnGhost}
          >
            Change
          </button>
        </div>
      )}

      <div className="mb-4 grid grid-cols-3 gap-2">
        {(["friends", "requests", "add"] as const).map((x) => (
          <button
            key={x}
            type="button"
            onClick={() => setTab(x)}
            data-testid={`friends-tab-${x}`}
            className={`rounded-xl border px-2 py-2 text-xs font-semibold capitalize ${
              tab === x
                ? "border-brand-strong bg-[#FFF8E1] text-brand"
                : "border-border bg-surface text-muted"
            }`}
          >
            {x === "requests" && incoming > 0 ? `Requests (${incoming})` : x}
          </button>
        ))}
      </div>

      {!data ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : tab === "friends" ? (
        data.friends.length === 0 ? (
          <p data-testid="friends-empty" className="py-8 text-center text-sm text-muted">
            No friends yet — add someone from the Add tab.
          </p>
        ) : (
          <div className="space-y-2">
            {data.friends.map((e) => (
              <PersonRow key={e.id} user={e.user} testId={`friend-${e.user.user_id}`}>
                <button
                  type="button"
                  onClick={() => router.push(`/stats?player=${e.user.user_id}`)}
                  data-testid={`friend-stats-${e.user.user_id}`}
                  className={btnGhost}
                >
                  Stats
                </button>
                <button
                  type="button"
                  disabled={busy === e.user.user_id}
                  onClick={() =>
                    act(e.user.user_id, () => friendsApi.remove(e.user.user_id), "Removed.")
                  }
                  data-testid={`friend-remove-${e.user.user_id}`}
                  className={btnGhost}
                >
                  Remove
                </button>
              </PersonRow>
            ))}
          </div>
        )
      ) : tab === "requests" ? (
        <div className="space-y-4">
          <section className="space-y-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Received</p>
            {data.incoming.length === 0 ? (
              <p className="text-sm text-muted">Nothing waiting on you.</p>
            ) : (
              data.incoming.map((e) => (
                <PersonRow key={e.id} user={e.user} testId={`incoming-${e.id}`}>
                  <button
                    type="button"
                    disabled={busy === e.id}
                    onClick={() => act(e.id, () => friendsApi.accept(e.id), "Friend added.")}
                    data-testid={`accept-${e.id}`}
                    className={btnPrimary}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    disabled={busy === e.id}
                    onClick={() => act(e.id, () => friendsApi.dismiss(e.id))}
                    data-testid={`decline-${e.id}`}
                    className={btnGhost}
                  >
                    Decline
                  </button>
                </PersonRow>
              ))
            )}
          </section>
          <section className="space-y-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Sent</p>
            {data.outgoing.length === 0 ? (
              <p className="text-sm text-muted">None outstanding.</p>
            ) : (
              data.outgoing.map((e) => (
                <PersonRow key={e.id} user={e.user} sub="Waiting for them" testId={`outgoing-${e.id}`}>
                  <button
                    type="button"
                    disabled={busy === e.id}
                    onClick={() => act(e.id, () => friendsApi.dismiss(e.id))}
                    data-testid={`cancel-${e.id}`}
                    className={btnGhost}
                  >
                    Cancel
                  </button>
                </PersonRow>
              ))
            )}
          </section>
        </div>
      ) : (
        <div className="space-y-4">
          <form onSubmit={runSearch} className="space-y-2">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              data-testid="friend-search-input"
              placeholder="@username or email"
              className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none focus:border-brand-strong"
            />
            <button
              type="submit"
              disabled={busy === "search" || !query.trim()}
              data-testid="friend-search-btn"
              className="w-full rounded-xl bg-brand py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              Search
            </button>
            {/* Exact match only, so say so rather than letting a typo look
                like "this person doesn't exist". */}
            <p className="text-center text-[10px] text-muted">
              Matches a full username or email address exactly.
            </p>
          </form>

          {results !== null && (
            <section className="space-y-2">
              <p className="text-[10px] uppercase tracking-wider text-muted">Results</p>
              {results.length === 0 ? (
                <p data-testid="search-empty" className="text-sm text-muted">
                  Nobody found. Check the spelling, or add them from a game below.
                </p>
              ) : (
                results.map((u) => (
                  <PersonRow key={u.user_id} user={u} testId={`result-${u.user_id}`}>
                    <button
                      type="button"
                      disabled={busy === u.user_id}
                      onClick={() =>
                        act(u.user_id, () => friendsApi.sendRequest(u.user_id), "Request sent.")
                      }
                      data-testid={`add-${u.user_id}`}
                      className={btnPrimary}
                    >
                      Add
                    </button>
                  </PersonRow>
                ))
              )}
            </section>
          )}

          <section className="space-y-2">
            <p className="text-[10px] uppercase tracking-wider text-muted">Played with</p>
            {suggestions.length === 0 ? (
              <p data-testid="suggestions-empty" className="text-sm text-muted">
                Nobody new — everyone you&apos;ve played with is already connected.
              </p>
            ) : (
              suggestions.map((u) => (
                <PersonRow key={u.user_id} user={u} testId={`suggestion-${u.user_id}`}>
                  <button
                    type="button"
                    disabled={busy === u.user_id}
                    onClick={() =>
                      act(u.user_id, () => friendsApi.sendRequest(u.user_id), "Request sent.")
                    }
                    data-testid={`add-${u.user_id}`}
                    className={btnPrimary}
                  >
                    Add
                  </button>
                </PersonRow>
              ))
            )}
          </section>
        </div>
      )}
    </main>
  );
}
