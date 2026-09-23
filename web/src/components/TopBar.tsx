"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { request } from "@/lib/api";
import { signOut } from "@/lib/auth";
import { friendsApi } from "@/lib/friendsApi";
import type { MyProfile } from "@/lib/friendsTypes";

interface Notification {
  kind: "debt_to_pay" | "debt_to_approve" | "friend_request";
  counterparty: string;
  counterparty_username: string | null;
  amount_cents: number | null;
  ref_id: string;
}

/** Handles are how people refer to each other here, so lead with one and
 * keep the display name as the fallback. */
function who(n: Notification): string {
  return n.counterparty_username ? `@${n.counterparty_username}` : n.counterparty;
}

function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

function describe(n: Notification): string {
  switch (n.kind) {
    case "debt_to_pay":
      return `You owe ${who(n)} ${money(n.amount_cents ?? 0)}`;
    case "debt_to_approve":
      return `${who(n)} says they paid you ${money(n.amount_cents ?? 0)}`;
    case "friend_request":
      return `${who(n)} wants to be friends`;
  }
}

const hrefFor = (n: Notification) => (n.kind === "friend_request" ? "/friends" : "/debts");

/** Closes a panel on an outside tap or Escape — the two things people
 * reflexively do, and the difference between a dropdown and a trap. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

/** Hand-drawn rather than an emoji: emoji render differently on every
 * platform and this app doesn't use them. */
function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M18 8A6 6 0 1 0 6 8c0 5-2 6-2 6h16s-2-1-2-6Z"
        stroke="var(--brand)"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M13.7 18a2 2 0 0 1-3.4 0"
        stroke="var(--brand)"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

const panel =
  "absolute right-0 top-12 z-20 w-60 overflow-hidden rounded-xl border border-border bg-surface shadow-lg";
const item = "block w-full px-4 py-2.5 text-left text-sm text-foreground hover:bg-background";

/**
 * The account bubble and the bell.
 *
 * Both live here so the home screen can stay down to the two things you
 * actually came to do. Everything account-shaped (your stats, your games,
 * your debts, settings, signing out) hangs off your name; everything
 * waiting on you hangs off the bell.
 */
export default function TopBar() {
  const router = useRouter();
  const [profile, setProfile] = useState<MyProfile | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));
  const bellRef = useDismiss(bellOpen, () => setBellOpen(false));

  useEffect(() => {
    let cancelled = false;
    // One request each, and the bell is a single endpoint rather than
    // asking /debts and /friends separately — see notifications_service.
    Promise.all([
      friendsApi.me(),
      request<{ items: Notification[]; total: number }>("/notifications"),
    ])
      .then(([me, bell]) => {
        if (cancelled) return;
        setProfile(me);
        setNotifications(bell.items);
      })
      .catch(() => {
        /* the page below works fine without a top bar */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const go = (href: string) => {
    setMenuOpen(false);
    setBellOpen(false);
    router.push(href);
  };

  return (
    <div className="mb-6 flex items-center justify-end gap-2">
      <div className="relative" ref={bellRef}>
        <button
          onClick={() => {
            setBellOpen(!bellOpen);
            setMenuOpen(false);
          }}
          data-testid="bell-btn"
          aria-label={`Notifications${notifications.length ? `, ${notifications.length} pending` : ""}`}
          className="relative flex h-10 w-10 items-center justify-center rounded-full border border-border bg-surface text-base"
        >
          <BellIcon />
          {notifications.length > 0 && (
            <span
              data-testid="bell-count"
              className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white"
            >
              {notifications.length}
            </span>
          )}
        </button>
        {bellOpen && (
          <div className={panel} data-testid="bell-panel">
            {notifications.length === 0 ? (
              <p className="px-4 py-3 text-sm text-muted">Nothing needs you right now.</p>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.ref_id}
                  onClick={() => go(hrefFor(n))}
                  data-testid={`notification-${n.kind}`}
                  className={item}
                >
                  {describe(n)}
                </button>
              ))
            )}
          </div>
        )}
      </div>

      <div className="relative" ref={menuRef}>
        <button
          onClick={() => {
            setMenuOpen(!menuOpen);
            setBellOpen(false);
          }}
          data-testid="account-btn"
          className="flex h-10 items-center gap-2 rounded-full border border-border bg-surface pl-1 pr-3"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand text-xs font-bold text-white">
            {(profile?.username ?? profile?.display_name ?? "?").slice(0, 2).toUpperCase()}
          </span>
          <span data-testid="account-name" className="max-w-24 truncate text-xs font-semibold text-brand">
            {profile?.username ? `@${profile.username}` : (profile?.display_name ?? "…")}
          </span>
        </button>
        {menuOpen && (
          <div className={panel} data-testid="account-menu">
            <button onClick={() => go("/stats")} data-testid="menu-stats" className={item}>
              My Stats
            </button>
            <button onClick={() => go("/history")} data-testid="menu-games" className={item}>
              My Games
            </button>
            <button onClick={() => go("/debts")} data-testid="menu-debts" className={item}>
              My Debts
            </button>
            <button onClick={() => go("/settings")} data-testid="menu-settings" className={item}>
              Settings
            </button>
            <button
              onClick={async () => {
                await signOut();
                setMenuOpen(false);
                router.refresh();
                router.push("/");
              }}
              data-testid="menu-sign-out"
              className={`${item} border-t border-border text-muted`}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
