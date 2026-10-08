"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { groupsApi } from "@/lib/groupsApi";
import type { GroupSummary } from "@/lib/groupsTypes";
import { RowsSkeleton } from "@/components/Skeleton";

const inputCls =
  "min-w-0 flex-1 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm outline-none focus:border-brand-strong";
const sideBtn =
  "shrink-0 rounded-xl border border-brand-strong px-4 text-sm font-semibold text-brand disabled:opacity-50";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** A group's invite link carries the code; a pasted link works here too. */
function codeFrom(raw: string): string {
  const t = raw.trim();
  const m = t.match(/groups\/join\/([^/?#\s]+)/);
  return (m ? m[1] : t).toUpperCase();
}

export default function GroupsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [groups, setGroups] = useState<GroupSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    groupsApi
      .list()
      .then((r) => !cancelled && setGroups(r.groups))
      .catch((e) => !cancelled && setLoadError(e instanceof ApiError ? e.message : "Couldn't load groups."));
    return () => {
      cancelled = true;
    };
  }, [user]);

  async function act(fn: () => Promise<{ group_id: string }>) {
    setBusy(true);
    setError(null);
    try {
      const g = await fn();
      router.push(`/groups/${g.group_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That didn't go through.");
      setBusy(false);
    }
  }

  if (!user) return null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-6 flex items-center gap-3">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          aria-label="Back"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Groups</h1>
      </div>

      <div className="space-y-6">
        {loadError ? (
          <p className="text-center text-sm text-danger">{loadError}</p>
        ) : !groups ? (
          <RowsSkeleton rows={2} />
        ) : groups.length === 0 ? (
          <p data-testid="groups-empty" className="py-4 text-center text-sm text-muted">
            No groups yet.
          </p>
        ) : (
          <div className="space-y-2">
            {groups.map((g) => (
              <button
                key={g.group_id}
                onClick={() => router.push(`/groups/${g.group_id}`)}
                data-testid="group-row"
                data-group={g.name}
                className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-left"
              >
                <p className="truncate text-sm font-semibold text-foreground">{g.name}</p>
                <p className="text-xs text-muted">
                  {g.member_count} member{g.member_count === 1 ? "" : "s"} · {g.games_played} game
                  {g.games_played === 1 ? "" : "s"}
                  {g.last_played ? ` · ${formatDate(g.last_played)}` : ""}
                </p>
              </button>
            ))}
          </div>
        )}

        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest text-muted">New group</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const n = name.trim();
              if (n) act(() => groupsApi.create(n));
            }}
            className="flex gap-2"
          >
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              placeholder="Group name"
              data-testid="group-name-input"
              className={inputCls}
            />
            <button type="submit" disabled={busy || !name.trim()} data-testid="create-group-btn" className={sideBtn}>
              Create
            </button>
          </form>
        </div>

        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest text-muted">Join with a code</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const c = codeFrom(code);
              if (c) act(() => groupsApi.join(c));
            }}
            className="flex gap-2"
          >
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="CODE"
              autoCapitalize="characters"
              autoCorrect="off"
              data-testid="group-code-input"
              className={`${inputCls} uppercase tracking-[0.2em]`}
            />
            <button type="submit" disabled={busy || !code.trim()} data-testid="join-group-btn" className={sideBtn}>
              Join
            </button>
          </form>
        </div>

        {error && (
          <p data-testid="groups-error" className="text-center text-sm text-danger">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
