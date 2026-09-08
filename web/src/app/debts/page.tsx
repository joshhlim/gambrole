"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { debtsApi } from "@/lib/debtsApi";
import type { DebtView } from "@/lib/debtsTypes";
import { usePolling } from "@/lib/usePolling";

type Tab = "owing" | "owed";

function dollars(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function OwingRow({
  debt,
  onMarkPaid,
  busy,
}: {
  debt: DebtView;
  onMarkPaid: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div
      data-testid={`debt-owing-${debt.settlement_id}`}
      className="rounded-xl border border-border bg-surface px-4 py-3"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">
            {debt.counterparty_display_name}
          </p>
          <p className="text-xs text-muted">
            {capitalize(debt.game_type)} · {formatDate(debt.created_at)}
          </p>
        </div>
        <p className="text-lg font-bold text-danger">{dollars(debt.amount_cents)}</p>
      </div>
      <div className="mt-2">
        {debt.status === "pending" && (
          <button
            type="button"
            onClick={() => onMarkPaid(debt.settlement_id)}
            disabled={busy}
            data-testid={`mark-paid-btn-${debt.settlement_id}`}
            className="w-full rounded-lg bg-brand py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            Mark Paid
          </button>
        )}
        {debt.status === "marked_paid" && (
          <p className="text-xs text-muted">Waiting for {debt.counterparty_display_name} to approve.</p>
        )}
        {debt.status === "approved" && <p className="text-xs text-muted">Settled</p>}
      </div>
    </div>
  );
}

function OwedRow({
  debt,
  onApprove,
  onReject,
  busy,
}: {
  debt: DebtView;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  busy: boolean;
}) {
  const needsApproval = debt.status === "marked_paid";
  return (
    <div
      data-testid={`debt-owed-${debt.settlement_id}`}
      className={`rounded-xl border px-4 py-3 ${
        needsApproval ? "border-brand-strong bg-[#FFF8E1]" : "border-border bg-surface"
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">
            {debt.counterparty_display_name}
          </p>
          <p className="text-xs text-muted">
            {capitalize(debt.game_type)} · {formatDate(debt.created_at)}
          </p>
        </div>
        <p className="text-lg font-bold text-brand-strong">{dollars(debt.amount_cents)}</p>
      </div>
      <div className="mt-2">
        {debt.status === "pending" && <p className="text-xs text-muted">Not yet marked paid.</p>}
        {needsApproval && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => onApprove(debt.settlement_id)}
              disabled={busy}
              data-testid={`approve-btn-${debt.settlement_id}`}
              className="flex-1 rounded-lg bg-brand py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              Approve
            </button>
            <button
              type="button"
              onClick={() => onReject(debt.settlement_id)}
              disabled={busy}
              data-testid={`reject-btn-${debt.settlement_id}`}
              className="flex-1 rounded-lg border border-border py-2 text-xs font-semibold text-muted disabled:opacity-50"
            >
              Reject
            </button>
          </div>
        )}
        {debt.status === "approved" && <p className="text-xs text-muted">Settled</p>}
      </div>
    </div>
  );
}

export default function DebtsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [tab, setTab] = useState<Tab>("owing");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, error, setData } = usePolling(() => debtsApi.getMine(), 10000, [user]);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  if (!user) return null;

  async function runAction(
    settlementId: string,
    fn: (id: string) => Promise<{ settlement_id: string; status: string; updated_at: string }>,
    tabKey: Tab,
  ) {
    setBusyId(settlementId);
    setActionError(null);
    try {
      const result = await fn(settlementId);
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          [tabKey]: prev[tabKey].map((d) =>
            d.settlement_id === settlementId
              ? { ...d, status: result.status as DebtView["status"], updated_at: result.updated_at }
              : d,
          ),
        };
      });
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "That action didn't go through.");
    } finally {
      setBusyId(null);
    }
  }

  const needsApprovalCount = data?.owed.filter((d) => d.status === "marked_paid").length ?? 0;

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
        <h1 className="text-lg font-extrabold text-brand">Debts</h1>
      </div>

      {(error || actionError) && (
        <p data-testid="debts-error" className="text-sm text-center text-danger mb-4">
          {actionError ?? "Couldn't load debts."}
        </p>
      )}

      {!data ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setTab("owing")}
              data-testid="debts-tab-owing"
              className={`rounded-xl border px-2 py-2 text-xs font-semibold ${
                tab === "owing"
                  ? "border-brand-strong bg-[#FFF8E1] text-brand"
                  : "border-border bg-surface text-muted"
              }`}
            >
              You Owe
            </button>
            <button
              type="button"
              onClick={() => setTab("owed")}
              data-testid="debts-tab-owed"
              className={`rounded-xl border px-2 py-2 text-xs font-semibold ${
                tab === "owed"
                  ? "border-brand-strong bg-[#FFF8E1] text-brand"
                  : "border-border bg-surface text-muted"
              }`}
            >
              Owed To You{needsApprovalCount > 0 ? ` (${needsApprovalCount})` : ""}
            </button>
          </div>

          {tab === "owing" &&
            (data.owing.length === 0 ? (
              <p className="text-center text-sm text-muted py-8">You don&apos;t owe anyone.</p>
            ) : (
              <div className="space-y-3">
                {data.owing.map((debt) => (
                  <OwingRow
                    key={debt.settlement_id}
                    debt={debt}
                    busy={busyId === debt.settlement_id}
                    onMarkPaid={(id) => runAction(id, debtsApi.markPaid, "owing")}
                  />
                ))}
              </div>
            ))}

          {tab === "owed" &&
            (data.owed.length === 0 ? (
              <p className="text-center text-sm text-muted py-8">No one owes you anything.</p>
            ) : (
              <div className="space-y-3">
                {data.owed.map((debt) => (
                  <OwedRow
                    key={debt.settlement_id}
                    debt={debt}
                    busy={busyId === debt.settlement_id}
                    onApprove={(id) => runAction(id, debtsApi.approve, "owed")}
                    onReject={(id) => runAction(id, debtsApi.reject, "owed")}
                  />
                ))}
              </div>
            ))}
        </div>
      )}
    </main>
  );
}
