"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { request } from "@/lib/api";
import { signOut, useStoredUser } from "@/lib/auth";
import { friendsApi } from "@/lib/friendsApi";
import { money } from "@/lib/format";
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
  return n.counterparty_username
    ? `@${n.counterparty_username}`
    : n.counterparty;
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

const hrefFor = (n: Notification) =>
  n.kind === "friend_request" ? "/friends" : "/debts";

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

function ChevronIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="m6 9 6 6 6-6"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The home hero's tile at bar size. Just the mark — the wordmark next to
 *  it would crowd a 56px strip and it's already on the page you land on. */
function Logo() {
  return (
    <span className="flex h-8 w-8 rotate-3 items-center justify-center rounded-lg bg-brand shadow-sm shadow-brand/25">
      <span className="font-display text-lg font-extrabold leading-none text-gold-bright">
        G
      </span>
    </span>
  );
}

// Anchored to the bar, not to the button that opened it: the bell sits
// left of your name, so a panel hung off the bell's right edge ran past the
// left side of a narrow phone. Right-aligned to the bar's padding and
// capped at its inner width, it always fits.
const panel =
  "absolute right-5 top-13 z-20 w-60 max-w-[calc(100%-2.5rem)] overflow-hidden rounded-xl border border-border bg-surface shadow-lg";
const item =
  "block w-full px-4 py-2.5 text-left text-sm text-foreground hover:bg-background";

/** How long a bell count is allowed to be trusted before a navigation is
 *  worth spending a request on. Long enough that moving quickly between
 *  pages doesn't refetch each time, short enough that paying a debt is
 *  reflected by the time you're back. */
const BELL_TTL_MS = 5000;

/**
 * The one fixed thing on screen: logo, bell, your handle.
 *
 * Mounted in the root layout rather than per page, and deliberately
 * outside RouteTransition — pages slide underneath it, it doesn't travel
 * with them. Everything account-shaped (your stats, your games, your
 * debts, settings, signing out) hangs off your name; everything waiting
 * on you hangs off the bell; the logo is always the way home.
 */
export default function TopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, checked } = useStoredUser();
  // Tagged with whose they are: the bar outlives sign-out and account
  // switches, and must never show one account's handle or debts to the
  // next person signing in on the same phone.
  const [loaded, setLoaded] = useState<{
    userId: string;
    profile: MyProfile;
    notifications: Notification[];
  } | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const fetched = useRef<{ userId: string; at: number } | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const menuRef = useDismiss(menuOpen, () => setMenuOpen(false));
  const bellRef = useDismiss(bellOpen, () => setBellOpen(false));
  const accountBtnRef = useRef<HTMLButtonElement>(null);
  const menuPanelRef = useRef<HTMLDivElement>(null);

  // A menu opened from the keyboard should be usable from the keyboard:
  // focus lands on its first item, arrows move, Escape hands focus back.
  useEffect(() => {
    if (menuOpen) menuPanelRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [menuOpen]);

  function onMenuKey(e: React.KeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    );
    const at = items.indexOf(document.activeElement as HTMLElement);
    const move = (i: number) => {
      e.preventDefault();
      items[(i + items.length) % items.length]?.focus();
    };
    if (e.key === "ArrowDown") move(at + 1);
    else if (e.key === "ArrowUp") move(at - 1);
    else if (e.key === "Home") move(0);
    else if (e.key === "End") move(items.length - 1);
    else if (e.key === "Escape") {
      setMenuOpen(false);
      accountBtnRef.current?.focus();
    }
  }

  const mine = loaded && user && loaded.userId === user.user_id ? loaded : null;
  const profile = mine?.profile ?? null;
  const notifications = mine?.notifications ?? [];

  // The bar lives in the layout and never unmounts, so unlike a per-page
  // component it can't rely on remounting to refresh. Re-check on each
  // navigation — rate-limited, since the database is a long way off and a
  // slightly late badge is much cheaper than a request per hop.
  useEffect(() => {
    if (!user) return;
    const userId = user.user_id;
    // The TTL only applies to the same account — a different one signing
    // in fetches straight away.
    const last = fetched.current;
    if (last && last.userId === userId && Date.now() - last.at < BELL_TTL_MS) return;
    fetched.current = { userId, at: Date.now() };
    let cancelled = false;
    // One request for the bell rather than asking /debts and /friends
    // separately — see notifications_service.
    Promise.all([
      friendsApi.me(),
      request<{ items: Notification[]; total: number }>("/notifications"),
    ])
      .then(([me, bell]) => {
        if (cancelled) return;
        setLoaded({ userId, profile: me, notifications: bell.items });
      })
      .catch(() => {
        /* the page below works fine without a top bar */
      });
    return () => {
      cancelled = true;
    };
  }, [user, pathname]);

  // The bar only paints a ground once there's something passing under it.
  // At rest it's transparent, so the drifting backdrop runs unbroken from
  // the top of the screen instead of meeting a seam 56px down.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    // Read once per page too: arriving at a restored scroll position
    // fires no event, and landing at the top has to clear the last page's.
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [pathname]);

  // Nothing to show before we know who you are, or when you're signed out.
  if (!checked || !user) return null;

  const go = (href: string) => {
    setMenuOpen(false);
    setBellOpen(false);
    router.push(href);
  };

  return (
    // Sticky rather than merely first-in-the-document: on a long page
    // (stats, a game log) the way out shouldn't be a scroll away. The
    // translucent ground keeps content legible as it passes underneath.
    <header
      data-testid="top-bar"
      className={`sticky top-0 z-30 border-b transition-colors duration-200 ${
        scrolled
          ? "border-border/60 bg-background/80 backdrop-blur"
          : "border-transparent"
      }`}
    >
      <div className="relative mx-auto flex h-14 w-full max-w-md items-center justify-between px-5">
        <button
          onClick={() => go("/")}
          data-testid="logo-home-btn"
          aria-label="Home"
        >
          <Logo />
        </button>

        <div className="flex items-center gap-1">
          <div ref={bellRef}>
            <button
              onClick={() => {
                setBellOpen(!bellOpen);
                setMenuOpen(false);
              }}
              data-testid="bell-btn"
              aria-haspopup="true"
              aria-expanded={bellOpen}
              aria-controls="bell-panel"
              aria-label={`Notifications${notifications.length ? `, ${notifications.length} pending` : ""}`}
              className="relative flex h-10 w-10 items-center justify-center"
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
              <div id="bell-panel" className={panel} data-testid="bell-panel">
                {notifications.length === 0 ? (
                  <p className="px-4 py-3 text-sm text-muted">
                    Nothing needs you right now.
                  </p>
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

          <div ref={menuRef}>
            <button
              ref={accountBtnRef}
              onClick={() => {
                setMenuOpen(!menuOpen);
                setBellOpen(false);
              }}
              data-testid="account-btn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-controls="account-menu"
              className="flex h-10 items-center gap-1 pl-1 text-brand"
            >
              <span
                data-testid="account-name"
                className="max-w-28 truncate text-sm font-semibold"
              >
                {profile?.username
                  ? `@${profile.username}`
                  : (profile?.display_name ?? "…")}
              </span>
              <ChevronIcon />
            </button>
            {menuOpen && (
              <div
                id="account-menu"
                ref={menuPanelRef}
                role="menu"
                className={panel}
                data-testid="account-menu"
                onKeyDown={onMenuKey}
              >
                <button
                  onClick={() => go("/stats")}
                  data-testid="menu-stats"
                  role="menuitem"
                  className={item}
                >
                  My Stats
                </button>
                <button
                  onClick={() => go("/history")}
                  data-testid="menu-games"
                  role="menuitem"
                  className={item}
                >
                  My Games
                </button>
                <button
                  onClick={() => go("/debts")}
                  data-testid="menu-debts"
                  role="menuitem"
                  className={item}
                >
                  My Debts
                </button>
                <button
                  onClick={() => go("/settings")}
                  data-testid="menu-settings"
                  role="menuitem"
                  className={item}
                >
                  Settings
                </button>
                <button
                  onClick={async () => {
                    await signOut();
                    setMenuOpen(false);
                    setLoaded(null);
                    fetched.current = null;
                    // signOut announces itself (see lib/auth.ts), so this
                    // bar and the home page both drop the session on their
                    // own — no reload needed to clear a component that
                    // now outlives every navigation.
                    router.push("/");
                  }}
                  data-testid="menu-sign-out"
                  role="menuitem"
                  className={`${item} border-t border-border text-muted`}
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
