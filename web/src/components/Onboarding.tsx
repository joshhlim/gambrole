"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { historyApi } from "@/lib/historyApi";
import { setMe, useMe } from "@/lib/me";
import { profileApi } from "@/lib/profileApi";

const STEPS: { title: string; body: string; icon: React.ReactNode }[] = [
  {
    title: "Game night, settled",
    body: "Keep score for Taidi and Mahjong as you play. GamBROle works out who owes whom.",
    icon: <span className="font-display text-4xl font-extrabold leading-none">G</span>,
  },
  {
    title: "Start or join a game",
    body: "Create a room and share its code. Everyone joins on their own phone.",
    icon: (
      <Icon>
        <rect x="6" y="3" width="12" height="18" rx="2.5" />
        <path d="M10 17.5h4" />
        <path d="M9.5 8.5h5M9.5 11.5h5" />
      </Icon>
    ),
  },
  {
    title: "Guests and groups",
    body: "Seat someone without the app as a guest. Play with the same people often? Make a group for a running leaderboard.",
    icon: (
      <Icon>
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 19a5.5 5.5 0 0 1 11 0" />
        <circle cx="17" cy="9.5" r="2.5" />
        <path d="M15.5 14.2A4.5 4.5 0 0 1 21 18.5" />
      </Icon>
    ),
  },
  {
    title: "Settle up",
    body: "When the host ends a game, debts land in My Debts. Mark them paid as you square up.",
    icon: (
      <Icon>
        <circle cx="12" cy="12" r="8.5" />
        <path d="m8.2 12.3 2.6 2.6 5-5.4" />
      </Icon>
    ),
  },
];

function Icon({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

/**
 * The first-run walkthrough: shown once, on home, to an account that has
 * neither seen it nor played. Skip and Done both mark it seen on the
 * account, so it doesn't follow you to another phone. Anyone who has
 * already played (accounts from before it existed) is marked seen quietly.
 */
export default function Onboarding() {
  const me = useMe();
  const pathname = usePathname();
  // Whose decision this is, so an account switch re-decides.
  const [decided, setDecided] = useState<{ userId: string; show: boolean } | null>(null);
  const [step, setStep] = useState(0);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const needed = !!me && !me.preferences.onboarded;
  const userId = me?.user_id ?? null;

  useEffect(() => {
    if (!needed || !userId) return;
    let cancelled = false;
    historyApi
      .getMine()
      .then((h) => {
        if (cancelled) return;
        if (h.games.length > 0) {
          markSeen();
          setDecided({ userId, show: false });
        } else {
          setDecided({ userId, show: true });
        }
      })
      .catch(() => {
        /* no walkthrough beats one shown on a guess */
      });
    return () => {
      cancelled = true;
    };
  }, [needed, userId]);

  const open = needed && pathname === "/" && decided?.userId === userId && decided.show;

  useEffect(() => {
    if (open) primaryRef.current?.focus({ focusVisible: false } as FocusOptions);
  }, [open, step]);

  if (!open) return null;

  function finish() {
    setDecided(userId ? { userId, show: false } : null);
    setStep(0);
    markSeen();
  }

  const last = step === STEPS.length - 1;
  const s = STEPS[step];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      data-testid="onboarding"
      onKeyDown={(e) => e.key === "Escape" && finish()}
      className="fixed inset-0 z-50 flex flex-col bg-background"
    >
      <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-[max(0.5rem,env(safe-area-inset-top))]">
        <div className="flex h-14 items-center justify-end">
          {!last && (
            <button
              type="button"
              onClick={finish}
              data-testid="onboarding-skip"
              className="-mr-3 flex h-11 min-w-11 items-center justify-center px-3 text-sm font-semibold text-muted"
            >
              Skip
            </button>
          )}
        </div>

        <div
          key={step}
          data-testid="onboarding-step"
          data-step={step}
          className="route-forward flex flex-1 flex-col items-center justify-center text-center"
        >
          <div className="mb-8 flex h-24 w-24 rotate-3 items-center justify-center rounded-3xl bg-tile text-gold-bright shadow-lg shadow-black/10">
            {s.icon}
          </div>
          <h2 id="onboarding-title" className="text-2xl font-extrabold text-brand">
            {s.title}
          </h2>
          <p className="mt-3 max-w-xs text-[15px] leading-relaxed text-muted">{s.body}</p>
        </div>

        <div className="space-y-6">
          <div className="flex justify-center gap-2" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            {STEPS.map((_, i) => (
              <span
                key={i}
                aria-hidden
                className={`h-2 rounded-full transition-all duration-300 ${
                  i === step ? "w-6 bg-brand-strong" : "w-2 bg-border"
                }`}
              />
            ))}
          </div>
          <div className="flex gap-3">
            {step > 0 && (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                data-testid="onboarding-back"
                className="h-12 flex-1 rounded-xl border border-border bg-surface text-sm font-semibold text-brand"
              >
                Back
              </button>
            )}
            <button
              ref={primaryRef}
              type="button"
              onClick={() => (last ? finish() : setStep(step + 1))}
              data-testid={last ? "onboarding-done" : "onboarding-next"}
              className="h-12 flex-[2] rounded-xl bg-primary text-sm font-semibold text-on-primary"
            >
              {last ? "Get started" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Seen, on the account. The overlay is already hidden locally (see
 * finish), so nothing waits on this; a failed save just means it may show
 * once more next time. */
function markSeen() {
  profileApi
    .setPreferences({ onboarded: true })
    .then(setMe)
    .catch(() => {});
}
