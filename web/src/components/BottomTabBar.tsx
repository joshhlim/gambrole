"use client";

import { usePathname, useRouter } from "next/navigation";
import { useStoredUser } from "@/lib/auth";

type TabId = "home" | "groups" | "play" | "debts" | "me";

/** Screens that take the whole display — a live table, a form you're in the
 * middle of, a link you followed — have their own way out and no tab bar. */
const IMMERSIVE = ["/room", "/new", "/play/join", "/auth", "/claim", "/groups/join"];

/** Which tab a screen belongs to, so the bar shows where you are even a
 * level or two down (a group's page is still Groups). */
function tabFor(pathname: string): TabId | null {
  if (pathname === "/") return "home";
  if (pathname.startsWith("/groups") || pathname === "/group") return "groups";
  if (pathname === "/play") return "play";
  if (pathname === "/debts") return "debts";
  if (["/me", "/stats", "/history", "/friends", "/settings"].includes(pathname)) return "me";
  return null;
}

// Hand-drawn rather than emoji, like the rest of the app's icons: emoji
// render differently on every platform.
const stroke = {
  stroke: "currentColor",
  strokeWidth: 1.9,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  fill: "none",
};

function Icon({ tab }: { tab: Exclude<TabId, "play"> }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden>
      {tab === "home" && (
        <path {...stroke} d="M3.5 10.5 12 3.8l8.5 6.7V19a1.5 1.5 0 0 1-1.5 1.5h-4v-6h-6v6H5A1.5 1.5 0 0 1 3.5 19z" />
      )}
      {tab === "groups" && (
        <>
          <circle {...stroke} cx="9" cy="8.5" r="3.2" />
          <path {...stroke} d="M3 19.5c.6-3.3 3-5 6-5s5.4 1.7 6 5" />
          <path {...stroke} d="M15.5 5.6a3.2 3.2 0 0 1 0 5.8M17.5 14.8c1.8.6 3 2.2 3.5 4.7" />
        </>
      )}
      {tab === "debts" && (
        <>
          <rect {...stroke} x="3" y="6" width="18" height="13" rx="2.5" />
          <path {...stroke} d="M3 10h18M7 15h4" />
        </>
      )}
      {tab === "me" && (
        <>
          <circle {...stroke} cx="12" cy="8.5" r="3.8" />
          <path {...stroke} d="M4.5 20c.9-3.8 3.9-5.8 7.5-5.8s6.6 2 7.5 5.8" />
        </>
      )}
    </svg>
  );
}

const TABS: { id: Exclude<TabId, "play">; label: string; href: string }[] = [
  { id: "home", label: "Home", href: "/" },
  { id: "groups", label: "Groups", href: "/groups" },
  { id: "debts", label: "Debts", href: "/debts" },
  { id: "me", label: "Me", href: "/me" },
];

/** Height of the bar above the home indicator — the spacer reserves it so
 * the bottom of every page can still scroll clear. */
const BAR_H = "h-16";

/**
 * The app's main way around: four tabs and a raised Play button in the
 * middle. Mounted once in the root layout, like the top bar; hidden when
 * signed out and on full-screen flows (IMMERSIVE).
 */
export default function BottomTabBar() {
  const router = useRouter();
  const pathname = usePathname();
  const { user, checked } = useStoredUser();
  if (!checked || !user || IMMERSIVE.some((p) => pathname === p || pathname.startsWith(`${p}/`))) {
    return null;
  }
  const current = tabFor(pathname);

  const tab = (t: (typeof TABS)[number]) => {
    const active = current === t.id;
    return (
      <button
        key={t.id}
        onClick={() => router.push(t.href)}
        data-testid={`tab-${t.id}`}
        aria-current={active ? "page" : undefined}
        className={`flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px] font-semibold transition-colors ${
          active ? "text-brand" : "text-muted"
        }`}
      >
        <Icon tab={t.id} />
        {t.label}
      </button>
    );
  };

  return (
    <>
      <div aria-hidden className={`${BAR_H} shrink-0`} />
      <nav
        data-testid="tab-bar"
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border/60 bg-background/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-lg"
      >
        <div className={`mx-auto flex ${BAR_H} w-full max-w-md items-stretch px-2`}>
          {tab(TABS[0])}
          {tab(TABS[1])}
          <div className="flex flex-1 items-start justify-center">
            <button
              onClick={() => router.push("/play")}
              data-testid="tab-play"
              aria-label="Play"
              aria-current={current === "play" ? "page" : undefined}
              className="-mt-5 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-on-primary shadow-lg shadow-black/20 ring-4 ring-background transition-transform active:scale-95"
            >
              <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden>
                <path d="M8 5.5v13l10.5-6.5z" fill="currentColor" />
              </svg>
            </button>
          </div>
          {tab(TABS[2])}
          {tab(TABS[3])}
        </div>
      </nav>
    </>
  );
}
