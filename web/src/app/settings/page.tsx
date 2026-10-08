"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getAccountEmail, updateDisplayName, updateEmail, updatePassword } from "@/lib/account";
import { passwordAuth, signOut, useStoredUser, type CurrentUser } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { friendsApi } from "@/lib/friendsApi";
import { ACCENTS, type MyProfile } from "@/lib/friendsTypes";
import { squareAvatar } from "@/lib/image";
import { loadMe, setMe, useMe } from "@/lib/me";
import {
  CURRENCY_SYMBOLS,
  getThemePref,
  setCurrencySymbol,
  setThemePref,
  useCurrencySymbol,
  useThemePref,
  type ThemePref,
} from "@/lib/preferences";
import { profileApi, profileHref, type PreferencesUpdate } from "@/lib/profileApi";
import { describeMahjongRules, describeTaidiRules } from "@/lib/rulesSummary";
import { forgetProfile } from "@/lib/useProfiles";
import Avatar, { accentColor } from "@/components/Avatar";

const inputCls =
  "w-full rounded-xl border border-border bg-background px-4 py-3 text-sm text-foreground outline-none focus:border-brand-strong";
const saveBtn =
  "min-h-11 shrink-0 rounded-xl bg-primary px-4 text-sm font-semibold text-on-primary disabled:opacity-50";
const quietBtn =
  "min-h-11 shrink-0 rounded-xl border border-border px-4 text-sm font-semibold text-brand disabled:opacity-50";
const label = "block text-xs font-medium text-muted";

const BIO_MAX = 160;
const CITY_MAX = 60;

function errorText(e: unknown, fallback: string): string {
  return e instanceof ApiError || e instanceof Error ? e.message : fallback;
}

/** A short-lived status line: "Saved." fades by itself; errors stay until
 * the next attempt. */
function useStatus() {
  const [status, setStatus] = useState<{ text: string; error: boolean } | null>(null);
  useEffect(() => {
    if (!status || status.error) return;
    const t = setTimeout(() => setStatus(null), 2500);
    return () => clearTimeout(t);
  }, [status]);
  return {
    status,
    saved: (text = "Saved.") => setStatus({ text, error: false }),
    failed: (text: string) => setStatus({ text, error: true }),
    clear: () => setStatus(null),
  };
}

/** Takes no room until there's something to say. */
function Status({ status, testId }: { status: { text: string; error: boolean } | null; testId?: string }) {
  if (!status) return null;
  return (
    <p role="status" data-testid={testId} className={`text-xs ${status.error ? "text-danger" : "text-brand-strong"}`}>
      {status.text}
    </p>
  );
}

function Section({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <section data-testid={testId}>
      <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-widest text-muted">{title}</h2>
      <div className="divide-y divide-border rounded-2xl border border-border bg-surface">{children}</div>
    </section>
  );
}

function Row({ children }: { children: ReactNode }) {
  return <div className="space-y-2 px-4 py-4">{children}</div>;
}

/** Two or three mutually exclusive choices, all visible at once. */
function Segmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  testIdPrefix,
}: {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel: string;
  testIdPrefix: string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className="flex rounded-xl border border-border bg-background p-1">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => !on && onChange(o.value)}
            data-testid={`${testIdPrefix}-${o.value}`}
            className={`min-h-10 flex-1 rounded-lg px-2 text-sm font-semibold transition-colors ${
              on ? "bg-surface text-brand shadow-sm ring-1 ring-border" : "text-muted"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Switch({
  checked,
  onChange,
  label: text,
  testId,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      data-testid={testId}
      className="flex min-h-11 w-full items-center justify-between gap-3 text-left text-sm font-medium text-foreground"
    >
      <span>{text}</span>
      <span
        aria-hidden
        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors ${
          checked ? "bg-primary-strong" : "bg-border"
        }`}
      >
        <span
          className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${
            checked ? "translate-x-6" : "translate-x-1"
          }`}
        />
      </span>
    </button>
  );
}

function SettingsSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label="Loading settings">
      {[3, 2, 2].map((rows, i) => (
        <div key={i}>
          <div className="mb-2 ml-1 h-3 w-20 animate-pulse rounded bg-border" />
          <div className="space-y-4 rounded-2xl border border-border bg-surface px-4 py-4">
            {Array.from({ length: rows }, (_, j) => (
              <div key={j} className="h-10 animate-pulse rounded-xl bg-border/60" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const me = useMe();
  // Amounts in the saved-default summaries follow the symbol picked here.
  useCurrencySymbol();

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-8 flex items-center gap-3">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          aria-label="Back"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Settings</h1>
      </div>

      {!user || !me ? (
        <SettingsSkeleton />
      ) : (
        <div className="space-y-8">
          <ProfileSection me={me} user={user} />
          <AppearanceSection me={me} />
          <DefaultsSection me={me} />
          <PrivacySection me={me} />
          <AccountSection user={user} onSignedOut={() => router.push("/")} />
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Profile

function ProfileSection({ me, user }: { me: MyProfile; user: CurrentUser }) {
  return (
    <Section title="Profile" testId="settings-profile">
      <PhotoRow me={me} />
      {passwordAuth && <DisplayNameRow user={user} />}
      <UsernameRow me={me} />
      <AboutRow me={me} />
      <AccentRow me={me} />
    </Section>
  );
}

function PhotoRow({ me }: { me: MyProfile }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { status, saved, failed, clear } = useStatus();

  // The preview is a blob URL; let it go once it's no longer shown.
  useEffect(() => {
    if (!preview) return;
    return () => URL.revokeObjectURL(preview);
  }, [preview]);

  async function choose(file: File | undefined) {
    if (!file) return;
    clear();
    setBusy(true);
    let blob: Blob;
    try {
      blob = await squareAvatar(file);
    } catch (e) {
      failed(errorText(e, "Couldn't use that photo."));
      setBusy(false);
      return;
    }
    // Shown straight away; the saved one replaces it once it's up.
    setPreview(URL.createObjectURL(blob));
    try {
      setMe(await profileApi.setAvatar(blob));
      forgetProfile(me.user_id);
      saved();
    } catch (e) {
      failed(errorText(e, "Couldn't upload that photo."));
    } finally {
      setPreview(null);
      setBusy(false);
    }
  }

  async function remove() {
    clear();
    setBusy(true);
    const before = me;
    setMe({ ...me, avatar_url: null });
    try {
      setMe(await profileApi.removeAvatar());
      forgetProfile(me.user_id);
      saved("Removed.");
    } catch (e) {
      setMe(before);
      failed(errorText(e, "Couldn't remove it."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Row>
      <div className="flex items-center gap-4">
        <Avatar
          name={me.display_name}
          url={me.avatar_url}
          src={preview}
          accent={me.accent}
          size={72}
          className={busy ? "opacity-60" : ""}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold text-foreground">{me.display_name}</p>
          {me.username && <p className="truncate text-sm text-muted">@{me.username}</p>}
          <Link
            href={profileHref(me)}
            data-testid="settings-view-profile"
            className="mt-1 inline-flex min-h-8 items-center text-xs font-semibold text-brand-strong"
          >
            View profile
          </Link>
        </div>
      </div>
      <div className="flex gap-2">
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          data-testid="avatar-file-input"
          onChange={(e) => {
            choose(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          data-testid="avatar-change-btn"
          className={`${quietBtn} flex-1`}
        >
          {busy ? "Saving…" : me.avatar_url ? "Change photo" : "Add photo"}
        </button>
        {me.avatar_url && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            data-testid="avatar-remove-btn"
            className="min-h-11 shrink-0 rounded-xl border border-border px-4 text-sm font-semibold text-muted disabled:opacity-50"
          >
            Remove
          </button>
        )}
      </div>
      <Status status={status} testId="avatar-status" />
    </Row>
  );
}

function DisplayNameRow({ user }: { user: CurrentUser }) {
  const [name, setName] = useState(user.display_name);
  const [busy, setBusy] = useState(false);
  const { status, saved, failed } = useStatus();
  const trimmed = name.trim();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await updateDisplayName(trimmed);
      // The directory takes the new name from the next authenticated
      // /users/me, which is also what the top bar shows.
      loadMe(user.user_id, true).catch(() => {});
      saved();
    } catch (err) {
      failed(errorText(err, "Couldn't save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Row>
      <form onSubmit={save} className="space-y-2">
        <label htmlFor="settings-name" className={label}>
          Display name
        </label>
        <div className="flex gap-2">
          <input
            id="settings-name"
            data-testid="settings-name-input"
            className={inputCls}
            value={name}
            maxLength={40}
            onChange={(e) => setName(e.target.value)}
          />
          <button
            type="submit"
            disabled={busy || !trimmed || trimmed === user.display_name}
            data-testid="settings-save-name-btn"
            className={saveBtn}
          >
            Save
          </button>
        </div>
        <Status status={status} />
      </form>
    </Row>
  );
}

function UsernameRow({ me }: { me: MyProfile }) {
  const [value, setValue] = useState(me.username ?? "");
  const [busy, setBusy] = useState(false);
  const { status, saved, failed } = useStatus();
  const changed = value.trim().replace(/^@/, "").toLowerCase() !== (me.username ?? "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await friendsApi.setUsername(value);
      setValue(r.username);
      setMe({ ...me, username: r.username });
      saved(`Saved as @${r.username}.`);
    } catch (err) {
      failed(errorText(err, "Couldn't save that username."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Row>
      <form onSubmit={save} className="space-y-2">
        <label htmlFor="settings-username" className={label}>
          Username
        </label>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <span aria-hidden className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-sm text-muted">
              @
            </span>
            <input
              id="settings-username"
              data-testid="settings-username-input"
              className={`${inputCls} pl-8`}
              value={value}
              maxLength={25}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <button
            type="submit"
            disabled={busy || !value.trim() || !changed}
            data-testid="settings-save-username-btn"
            className={saveBtn}
          >
            Save
          </button>
        </div>
        <Status status={status} testId="settings-username-status" />
      </form>
    </Row>
  );
}

function AboutRow({ me }: { me: MyProfile }) {
  const [bio, setBio] = useState(me.bio ?? "");
  const [city, setCity] = useState(me.city ?? "");
  const [busy, setBusy] = useState(false);
  const { status, saved, failed } = useStatus();
  const changed = bio.trim() !== (me.bio ?? "") || city.trim() !== (me.city ?? "");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const next = await profileApi.update({ bio: bio.trim(), city: city.trim() });
      setMe(next);
      // The server tidies whitespace; show what it kept.
      setBio(next.bio ?? "");
      setCity(next.city ?? "");
      saved();
    } catch (err) {
      failed(errorText(err, "Couldn't save."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Row>
      <form onSubmit={save} className="space-y-3">
        <div className="space-y-2">
          <div className="flex items-baseline justify-between">
            <label htmlFor="settings-bio" className={label}>
              Bio
            </label>
            <span className={`text-[11px] tabular ${bio.length > BIO_MAX - 20 ? "text-gold-text" : "text-muted"}`}>
              {bio.length}/{BIO_MAX}
            </span>
          </div>
          <textarea
            id="settings-bio"
            data-testid="settings-bio-input"
            rows={3}
            maxLength={BIO_MAX}
            value={bio}
            onChange={(e) => setBio(e.target.value)}
            className={`${inputCls} resize-none leading-relaxed`}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="settings-city" className={label}>
            City
          </label>
          <input
            id="settings-city"
            data-testid="settings-city-input"
            maxLength={CITY_MAX}
            value={city}
            autoComplete="address-level2"
            onChange={(e) => setCity(e.target.value)}
            className={inputCls}
          />
        </div>
        <div className="flex items-center justify-between gap-3">
          <Status status={status} testId="settings-about-status" />
          <button
            type="submit"
            disabled={busy || !changed}
            data-testid="settings-save-about-btn"
            className={`${saveBtn} ml-auto`}
          >
            Save
          </button>
        </div>
      </form>
    </Row>
  );
}

function AccentRow({ me }: { me: MyProfile }) {
  const { status, saved, failed } = useStatus();

  // Saved on tap, shown before the server answers; put back if it refuses.
  async function pick(accent: string | null) {
    const before = me;
    setMe({ ...me, accent });
    try {
      setMe(await profileApi.update({ accent: accent ?? "" }));
      forgetProfile(me.user_id);
      saved();
    } catch (e) {
      setMe(before);
      failed(errorText(e, "Couldn't save."));
    }
  }

  const options: (string | null)[] = [null, ...ACCENTS];
  return (
    <Row>
      <p id="accent-label" className={label}>
        Colour
      </p>
      <div role="radiogroup" aria-labelledby="accent-label" className="flex flex-wrap gap-1">
        {options.map((a) => {
          const on = (me.accent ?? null) === a;
          return (
            <button
              key={a ?? "none"}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={a ?? "None"}
              title={a ? a.charAt(0).toUpperCase() + a.slice(1) : "None"}
              onClick={() => !on && pick(a)}
              data-testid={`accent-${a ?? "none"}`}
              className="flex h-10 w-10 items-center justify-center rounded-full"
            >
              <span
                className={`flex h-7 w-7 items-center justify-center rounded-full ${
                  a ? "" : "border-2 border-dashed border-border"
                } ${on ? "ring-2 ring-foreground ring-offset-2 ring-offset-surface" : ""}`}
                style={a ? { background: accentColor(a) ?? undefined } : undefined}
              />
            </button>
          );
        })}
      </div>
      <Status status={status} testId="settings-accent-status" />
    </Row>
  );
}

// ---------------------------------------------------------------------------
// Appearance

const THEMES = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;

/** Applies a preference change locally at once, saves it, and puts it back
 * if the save fails. Everything here is a single tap, so none of it waits. */
async function savePreference(
  me: MyProfile,
  changes: PreferencesUpdate,
  local: () => void,
  undo: () => void,
  status: ReturnType<typeof useStatus>,
) {
  local();
  setMe({ ...me, preferences: { ...me.preferences, ...(changes as Partial<MyProfile["preferences"]>) } });
  try {
    setMe(await profileApi.setPreferences(changes));
    status.saved();
  } catch (e) {
    undo();
    setMe(me);
    status.failed(errorText(e, "Couldn't save."));
  }
}

function AppearanceSection({ me }: { me: MyProfile }) {
  const theme = useThemePref();
  const symbol = useCurrencySymbol();
  const themeStatus = useStatus();
  const currencyStatus = useStatus();

  function chooseTheme(next: ThemePref) {
    const before = getThemePref();
    savePreference(
      me,
      { theme: next },
      () => setThemePref(next),
      () => setThemePref(before),
      themeStatus,
    );
  }

  function chooseSymbol(next: string) {
    const before = symbol;
    savePreference(
      me,
      { currency_symbol: next },
      () => setCurrencySymbol(next),
      () => setCurrencySymbol(before),
      currencyStatus,
    );
  }

  return (
    <Section title="Appearance" testId="settings-appearance">
      <Row>
        <p className={label}>Theme</p>
        <Segmented
          options={THEMES}
          value={theme}
          onChange={chooseTheme}
          ariaLabel="Theme"
          testIdPrefix="theme"
        />
        <Status status={themeStatus.status} testId="settings-theme-status" />
      </Row>
      <Row>
        <div className="flex items-center justify-between gap-3">
          <label htmlFor="settings-currency" className="text-sm font-medium text-foreground">
            Currency symbol
          </label>
          <select
            id="settings-currency"
            data-testid="settings-currency-select"
            value={symbol}
            onChange={(e) => chooseSymbol(e.target.value)}
            className="min-h-11 rounded-xl border border-border bg-background px-3 text-sm font-semibold text-foreground outline-none focus:border-brand-strong"
          >
            {CURRENCY_SYMBOLS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <Status status={currencyStatus.status} testId="settings-currency-status" />
      </Row>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Game defaults

function DefaultsSection({ me }: { me: MyProfile }) {
  const status = useStatus();
  const [busy, setBusy] = useState<string | null>(null);
  const saved = me.preferences.default_rules;
  const rows = [
    {
      game: "taidi" as const,
      label: "Taidi",
      summary: saved.taidi ? describeTaidiRules(saved.taidi) : null,
    },
    {
      game: "mahjong" as const,
      label: "Mahjong",
      summary: saved.mahjong ? describeMahjongRules(saved.mahjong) : null,
    },
  ];

  async function clearDefault(game: "taidi" | "mahjong") {
    setBusy(game);
    try {
      setMe(await profileApi.setPreferences({ default_rules: { [game]: null } }));
      status.saved("Cleared.");
    } catch (e) {
      status.failed(errorText(e, "Couldn't clear it."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section title="Default rules" testId="settings-defaults">
      {rows.map((r) => (
        <div key={r.game} data-testid={`default-rules-${r.game}`} className="flex items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-foreground">{r.label}</p>
            <p data-testid={`default-rules-${r.game}-summary`} className="text-xs leading-relaxed text-muted">
              {r.summary ?? (saved[r.game] ? "Saved" : "Not set")}
            </p>
          </div>
          {saved[r.game] ? (
            <button
              type="button"
              onClick={() => clearDefault(r.game)}
              disabled={busy === r.game}
              data-testid={`default-rules-${r.game}-clear`}
              className="min-h-11 shrink-0 rounded-xl border border-border px-3 text-xs font-semibold text-muted disabled:opacity-50"
            >
              Clear
            </button>
          ) : (
            <Link
              href="/new"
              className="flex min-h-11 shrink-0 items-center rounded-xl border border-border px-3 text-xs font-semibold text-brand"
            >
              Set up
            </Link>
          )}
        </div>
      ))}
      {status.status && (
        <div className="px-4 py-2">
          <Status status={status.status} />
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Privacy

const PROFILE_VISIBILITY = [
  { value: "everyone", label: "Everyone" },
  { value: "friends", label: "Friends" },
  { value: "nobody", label: "Nobody" },
] as const;

const STATS_VISIBILITY = [
  { value: "friends", label: "Friends" },
  { value: "nobody", label: "Nobody" },
] as const;

function PrivacySection({ me }: { me: MyProfile }) {
  const status = useStatus();

  async function change(changes: Partial<Pick<MyProfile, "profile_visibility" | "stats_visibility" | "searchable">>) {
    setMe({ ...me, ...changes });
    try {
      setMe(await profileApi.setPrivacy(changes));
      status.saved();
    } catch (e) {
      setMe(me);
      status.failed(errorText(e, "Couldn't save."));
    }
  }

  return (
    <Section title="Privacy" testId="settings-privacy">
      <Row>
        <p className={label}>Who sees your bio and city</p>
        <Segmented
          options={PROFILE_VISIBILITY}
          value={me.profile_visibility}
          onChange={(v) => change({ profile_visibility: v })}
          ariaLabel="Who sees your bio and city"
          testIdPrefix="profile-visibility"
        />
      </Row>
      <Row>
        <p className={label}>Who sees your stats</p>
        <Segmented
          options={STATS_VISIBILITY}
          value={me.stats_visibility}
          onChange={(v) => change({ stats_visibility: v })}
          ariaLabel="Who sees your stats"
          testIdPrefix="stats-visibility"
        />
      </Row>
      <div className="px-4 py-2">
        <Switch
          checked={me.searchable}
          onChange={(v) => change({ searchable: v })}
          label="Appear in search"
          testId="searchable-switch"
        />
      </div>
      {status.status && (
        <div className="px-4 py-2">
          <Status status={status.status} testId="settings-privacy-status" />
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Account

function AccountSection({ user, onSignedOut }: { user: CurrentUser; onSignedOut: () => void }) {
  const [email, setEmail] = useState<string | null>(null);
  const [emailChecked, setEmailChecked] = useState(!passwordAuth);

  useEffect(() => {
    if (!passwordAuth) return;
    let cancelled = false;
    getAccountEmail()
      .then((e) => !cancelled && setEmail(e))
      .catch(() => !cancelled && setEmail(null))
      .finally(() => !cancelled && setEmailChecked(true));
    return () => {
      cancelled = true;
    };
  }, [user.user_id]);

  async function handleSignOut() {
    await signOut();
    setMe(null);
    onSignedOut();
  }

  return (
    <Section title="Account" testId="settings-account">
      {passwordAuth &&
        (emailChecked ? (
          <AccountForms initialEmail={email ?? ""} />
        ) : (
          <Row>
            <div className="h-10 animate-pulse rounded-xl bg-border/60" />
          </Row>
        ))}
      <div className="px-4 py-3">
        <button
          onClick={handleSignOut}
          data-testid="settings-sign-out-btn"
          className="min-h-11 w-full rounded-xl text-sm font-semibold text-danger"
        >
          Sign out
        </button>
      </div>
    </Section>
  );
}

function AccountForms({ initialEmail }: { initialEmail: string }) {
  const [emailInput, setEmailInput] = useState(initialEmail);
  const [emailBusy, setEmailBusy] = useState(false);
  const emailStatus = useStatus();

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const passwordStatus = useStatus();

  async function handleSaveEmail(e: React.FormEvent) {
    e.preventDefault();
    setEmailBusy(true);
    try {
      await updateEmail(emailInput.trim());
      emailStatus.saved("Check your new email to confirm the change.");
    } catch (err) {
      emailStatus.failed(errorText(err, "Couldn't save."));
    } finally {
      setEmailBusy(false);
    }
  }

  async function handleSavePassword(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword.length < 6) {
      passwordStatus.failed("Password must be at least 6 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      passwordStatus.failed("Passwords don't match.");
      return;
    }
    setPasswordBusy(true);
    try {
      await updatePassword(newPassword);
      passwordStatus.saved("Password updated.");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      passwordStatus.failed(errorText(err, "Couldn't save."));
    } finally {
      setPasswordBusy(false);
    }
  }

  return (
    <>
      <Row>
        <form onSubmit={handleSaveEmail} className="space-y-2">
          <label htmlFor="settings-email" className={label}>
            Email
          </label>
          <div className="flex gap-2">
            <input
              id="settings-email"
              type="email"
              autoComplete="email"
              data-testid="settings-email-input"
              className={inputCls}
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
            />
            <button
              type="submit"
              disabled={emailBusy || !emailInput.trim() || emailInput.trim() === initialEmail}
              data-testid="settings-save-email-btn"
              className={saveBtn}
            >
              Save
            </button>
          </div>
          <Status status={emailStatus.status} />
        </form>
      </Row>
      <Row>
        <form onSubmit={handleSavePassword} className="space-y-2">
          <label htmlFor="settings-password" className={label}>
            New password
          </label>
          <input
            id="settings-password"
            type="password"
            autoComplete="new-password"
            data-testid="settings-new-password-input"
            placeholder="New password"
            className={inputCls}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <input
            type="password"
            autoComplete="new-password"
            aria-label="Confirm new password"
            data-testid="settings-confirm-password-input"
            placeholder="Confirm new password"
            className={inputCls}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
          <div className="flex items-center justify-between gap-3">
            <Status status={passwordStatus.status} />
            <button
              type="submit"
              disabled={passwordBusy || !newPassword}
              data-testid="settings-save-password-btn"
              className={`${saveBtn} ml-auto`}
            >
              Save
            </button>
          </div>
        </form>
      </Row>
    </>
  );
}
