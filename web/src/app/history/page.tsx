"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { historyApi } from "@/lib/historyApi";
import type { HistoryEntry, HistoryResponse } from "@/lib/historyTypes";

function dollars(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function GameCard({ game }: { game: HistoryEntry }) {
  return (
    <div
      data-testid={`history-row-${game.room_id}`}
      className="rounded-xl border border-border bg-surface px-4 py-3"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">{capitalize(game.game_type)}</p>
          <p className="text-xs text-muted">{formatDate(game.ended_at)}</p>
        </div>
        <p
          className={`text-lg font-bold ${game.net_cents < 0 ? "text-danger" : "text-brand-strong"}`}
        >
          {dollars(game.net_cents)}
        </p>
      </div>
      {game.settlements_total > 0 && (
        <div className="mt-2 flex items-center gap-2">
          {game.all_settled ? (
            <p className="text-xs text-muted">All settled</p>
          ) : (
            <p className="text-xs text-danger">
              {game.settlements_pending} debt{game.settlements_pending === 1 ? "" : "s"} pending
            </p>
          )}
          {game.settlements_needs_my_approval > 0 && (
            <span className="rounded-full bg-[#FFF8E1] px-2 py-0.5 text-xs font-semibold text-brand">
              {game.settlements_needs_my_approval} needs your approval
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    historyApi
      .getMine()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load history."));
  }, [user]);

  if (!user) return null;

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Game History</h1>
      </div>

      {error && (
        <p data-testid="history-error" className="text-sm text-center text-danger mb-4">
          {error}
        </p>
      )}

      {!data ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : data.games.length === 0 ? (
        <p data-testid="history-empty" className="text-center text-sm text-muted py-8">
          No finished games yet — play a room to see your history here.
        </p>
      ) : (
        <div className="space-y-3">
          {data.games.map((game) => (
            <GameCard key={game.room_id} game={game} />
          ))}
        </div>
      )}
    </main>
  );
}
