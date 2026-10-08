"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import { groupsApi } from "@/lib/groupsApi";
import type { GroupSummary } from "@/lib/groupsTypes";
import { mahjongApi } from "@/lib/mahjongApi";
import { useStoredUser } from "@/lib/auth";
import { setMe, useMe } from "@/lib/me";
import { useCurrencySymbol } from "@/lib/preferences";
import { profileApi } from "@/lib/profileApi";
import type { AnyRoomState, GameRules, GameType } from "@/lib/types";
import type { MahjongRules, TaiPayout } from "@/lib/mahjongTypes";

const DEFAULT_RULES: GameRules = {
  card_value_cents: 20,
  base_cards: 2,
  multipliers_enabled: true,
  double_threshold: 10,
  triple_threshold: 13,
  difference_payouts: true,
  special_hands_enabled: true,
  special_hand_cards: 5,
};

// "3/6 半" — a real Hong Kong-style stakes table, in cents. The tai payouts
// are non-linear (a 5-tai hand pays far more than 5x a 1-tai hand), so this
// is a lookup table rather than a per-tai rate.
const BAN_3_6_TABLE: Record<string, TaiPayout> = {
  1: { hu: 200, zimo: 200 },
  2: { hu: 350, zimo: 250 },
  3: { hu: 550, zimo: 350 },
  4: { hu: 1000, zimo: 600 },
  5: { hu: 2000, zimo: 1100 },
};

// Always cents_per_unit 1: without it the API reads the amounts as old
// $0.50 chips.
const DEFAULT_MAHJONG_RULES: MahjongRules = {
  cents_per_unit: 1,
  yao_amount: 100,
  gang_amount: 100,
  zimo_bonus_amount: 0,
  klppdd_amount: 0,
  max_tai: 5,
  tai_table: BAN_3_6_TABLE,
};

// "5/1 半" — higher stakes, more tai levels. Same non-linear-table shape
// as "3/6 半", plus a zimo bonus and KLPPDD on by default.
const BAN_5_1_TABLE: Record<string, TaiPayout> = {
  1: { hu: 200, zimo: 100 },
  2: { hu: 400, zimo: 200 },
  3: { hu: 800, zimo: 400 },
  4: { hu: 1600, zimo: 800 },
  5: { hu: 3200, zimo: 1600 },
  6: { hu: 6400, zimo: 3200 },
  7: { hu: 12800, zimo: 6400 },
};

const HIGH_STAKES_MAHJONG_RULES: MahjongRules = {
  cents_per_unit: 1,
  yao_amount: 150,
  gang_amount: 150,
  zimo_bonus_amount: 250,
  klppdd_amount: 250,
  max_tai: 7,
  tai_table: BAN_5_1_TABLE,
};

const MAHJONG_PRESETS: { label: string; rules: MahjongRules }[] = [
  { label: "3/6 半", rules: DEFAULT_MAHJONG_RULES },
  { label: "5/1 半", rules: HIGH_STAKES_MAHJONG_RULES },
];

const GAMES = [
  { id: "taidi", label: "Taidi", available: true },
  { id: "mahjong", label: "Mahjong", available: true },
  { id: "poker", label: "Poker", available: false },
] as const;

type GameId = (typeof GAMES)[number]["id"];

const inputCls =
  "w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand-strong aria-invalid:border-danger";

// ---------------------------------------------------------------------------
// The form keeps every number as the raw string typed. Parsing on each
// keystroke (Number(v) || 0) clobbered half-typed values like "0." and
// silently turned "-3" or "1.5" into something else; now what you typed
// stays on screen and is checked against the same limits the API enforces.

type Check = { value: number; error: null } | { value: null; error: string };

function wholeNumber(raw: string, min: number, max: number): Check {
  const t = raw.trim();
  if (t === "") return { value: null, error: "Required" };
  if (!/^\d+$/.test(t)) return { value: null, error: "Whole number" };
  const n = Number(t);
  if (n < min || n > max) return { value: null, error: `${min}–${max.toLocaleString()}` };
  return { value: n, error: null };
}

/** Dollars in, cents out: at most two decimals, $0 up to maxCents. */
function dollarsToCents(raw: string, maxCents = 10000): Check {
  const t = raw.trim();
  if (t === "") return { value: null, error: "Required" };
  if (!/^\d*(\.\d{0,2})?$/.test(t) || t === ".") return { value: null, error: "e.g. 0.20" };
  const cents = Math.round(Number(t) * 100);
  if (cents > maxCents) return { value: null, error: `Max ${money(maxCents)}` };
  return { value: cents, error: null };
}

const str = (n: number) => String(n);
const dollars = (cents: number) => (cents / 100).toFixed(2);

interface TaidiForm {
  cardValue: string;
  baseCards: string;
  multipliers: boolean;
  double: string;
  triple: string;
  difference: boolean;
  specials: boolean;
  specialCards: string;
}

function taidiForm(r: GameRules): TaidiForm {
  return {
    cardValue: dollars(r.card_value_cents),
    baseCards: str(r.base_cards),
    multipliers: r.multipliers_enabled,
    double: str(r.double_threshold),
    triple: str(r.triple_threshold),
    difference: r.difference_payouts,
    specials: r.special_hands_enabled,
    specialCards: str(r.special_hand_cards),
  };
}

function checkTaidi(f: TaidiForm) {
  const errors = {
    cardValue: dollarsToCents(f.cardValue).error,
    baseCards: wholeNumber(f.baseCards, 0, 52).error,
    double: null as string | null,
    triple: null as string | null,
    specialCards: null as string | null,
  };
  const cents = dollarsToCents(f.cardValue).value;
  const base = wholeNumber(f.baseCards, 0, 52).value;
  // Thresholds and the special-hand count only matter when their toggle is
  // on; while it's off they aren't checked and the defaults go instead.
  let double = DEFAULT_RULES.double_threshold;
  let triple = DEFAULT_RULES.triple_threshold;
  if (f.multipliers) {
    const d = wholeNumber(f.double, 1, 52);
    const t = wholeNumber(f.triple, 1, 52);
    errors.double = d.error;
    errors.triple = t.error ?? (d.value !== null && t.value! < d.value ? "At least ×2's" : null);
    double = d.value ?? double;
    triple = t.value ?? triple;
  }
  let special = DEFAULT_RULES.special_hand_cards;
  if (f.specials) {
    const sp = wholeNumber(f.specialCards, 0, 52);
    errors.specialCards = sp.error;
    special = sp.value ?? special;
  }
  const valid = Object.values(errors).every((e) => e === null);
  const rules: GameRules | null =
    valid && cents !== null && base !== null
      ? {
          card_value_cents: cents,
          base_cards: base,
          multipliers_enabled: f.multipliers,
          double_threshold: double,
          triple_threshold: triple,
          difference_payouts: f.difference,
          special_hands_enabled: f.specials,
          special_hand_cards: special,
        }
      : null;
  return { errors, rules };
}

// Mirror the API's caps (mahjong_core MAX_ACTION_AMOUNT, MAX_TAI_PAYOUT).
const MAX_TAI_LIMIT = 20;
const MAX_ACTION_CENTS = 100_000;
const MAX_TAI_CENTS = 1_000_000;

interface MahjongForm {
  yao: string;
  gang: string;
  zimoBonus: string;
  klppdd: string;
  maxTai: number;
  table: Record<string, { hu: string; zimo: string }>;
}

function mahjongForm(r: MahjongRules): MahjongForm {
  const table: MahjongForm["table"] = {};
  for (const [tai, p] of Object.entries(r.tai_table)) {
    table[tai] = { hu: dollars(p.hu), zimo: dollars(p.zimo) };
  }
  return {
    yao: dollars(r.yao_amount),
    gang: dollars(r.gang_amount),
    zimoBonus: dollars(r.zimo_bonus_amount),
    klppdd: dollars(r.klppdd_amount),
    maxTai: r.max_tai,
    table,
  };
}

function checkMahjong(f: MahjongForm) {
  const yao = dollarsToCents(f.yao, MAX_ACTION_CENTS);
  const gang = dollarsToCents(f.gang, MAX_ACTION_CENTS);
  const zimoBonus = dollarsToCents(f.zimoBonus, MAX_ACTION_CENTS);
  const klppdd = dollarsToCents(f.klppdd, MAX_ACTION_CENTS);
  const rows: Record<string, { hu: Check; zimo: Check }> = {};
  for (let t = 1; t <= f.maxTai; t++) {
    const row = f.table[t] ?? { hu: "", zimo: "" };
    rows[t] = {
      hu: dollarsToCents(row.hu, MAX_TAI_CENTS),
      zimo: dollarsToCents(row.zimo, MAX_TAI_CENTS),
    };
  }
  const all = [yao, gang, zimoBonus, klppdd, ...Object.values(rows).flatMap((r) => [r.hu, r.zimo])];
  const valid = all.every((c) => c.error === null);
  const rules: MahjongRules | null = valid
    ? {
        cents_per_unit: 1,
        yao_amount: yao.value!,
        gang_amount: gang.value!,
        zimo_bonus_amount: zimoBonus.value!,
        klppdd_amount: klppdd.value!,
        max_tai: f.maxTai,
        tai_table: Object.fromEntries(
          Object.entries(rows).map(([t, r]) => [t, { hu: r.hu.value!, zimo: r.zimo.value! }]),
        ),
      }
    : null;
  return {
    errors: {
      yao: yao.error,
      gang: gang.error,
      zimoBonus: zimoBonus.error,
      klppdd: klppdd.error,
      rows: Object.fromEntries(
        Object.entries(rows).map(([t, r]) => [t, { hu: r.hu.error, zimo: r.zimo.error }]),
      ),
    },
    rules,
  };
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <label className="block min-w-0">
      <span className="block text-xs text-muted mb-1">{label}</span>
      {children}
      {error && <span className="mt-0.5 block text-[11px] text-danger">{error}</span>}
    </label>
  );
}

/** A number field over a raw string — see the note above TaidiForm. */
function NumberInput({
  value,
  onChange,
  error,
  testId,
  decimal,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  error?: string | null;
  testId?: string;
  decimal?: boolean;
  label?: string;
}) {
  return (
    <input
      type="text"
      inputMode={decimal ? "decimal" : "numeric"}
      data-testid={testId}
      aria-label={label}
      aria-invalid={error ? true : undefined}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={inputCls}
    />
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3 text-sm cursor-pointer">
      <span className="font-medium">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-5 w-5 accent-brand-strong"
      />
    </label>
  );
}

/** Stashes the just-created room for the room page's first paint. Best
 * effort: the room exists either way, so a storage failure (private mode,
 * quota) must not turn into "Couldn't create a room". */
function stashFreshState(state: AnyRoomState) {
  try {
    sessionStorage.setItem(
      `gambrole_state_${state.room_id}`,
      JSON.stringify({ at: Date.now(), state }),
    );
  } catch {
    /* the room page just fetches it instead */
  }
}

/** useSearchParams() can't run during prerender, so the form that reads
 * ?group= sits under a Suspense boundary and the route stays static. */
export default function NewRoomPage() {
  return (
    <Suspense fallback={null}>
      <NewRoomForm />
    </Suspense>
  );
}

/** Which group the game counts towards. Hidden for anyone in no groups —
 * there's nothing to choose. */
function GroupSelect({
  groups,
  value,
  onChange,
}: {
  groups: GroupSummary[];
  value: string;
  onChange: (groupId: string) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <label className="mb-5 block">
      <span className="mb-1 block text-xs text-muted">Group</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid="group-select"
        className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none focus:border-brand-strong"
      >
        <option value="">None</option>
        {groups.map((g) => (
          <option key={g.group_id} value={g.group_id}>
            {g.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Keeps the form as it stands as your starting point for this game —
 * /new opens on it next time, and Settings shows (and clears) it. */
function SaveDefault({
  game,
  disabled,
  note,
  onSave,
}: {
  game: GameType;
  disabled: boolean;
  note: { text: string; error: boolean } | null;
  onSave: () => void;
}) {
  return (
    <div className="space-y-1 text-center">
      <button
        type="button"
        onClick={onSave}
        disabled={disabled}
        data-testid={`save-default-${game}`}
        className="min-h-11 w-full rounded-xl border border-border bg-surface text-sm font-semibold text-brand disabled:opacity-50"
      >
        Save as my default
      </button>
      {note && (
        <p
          role="status"
          data-testid="save-default-note"
          className={`text-xs ${note.error ? "text-danger" : "text-brand-strong"}`}
        >
          {note.text}
        </p>
      )}
    </div>
  );
}

function NewRoomForm() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  // Arriving from a group's "New game" preselects it; otherwise none.
  const wantedGroup = useSearchParams().get("group") ?? "";
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [groupId, setGroupId] = useState<string | null>(null);
  // A stale ?group= (you've left it) quietly falls back to none.
  const chosenGroup =
    groupId ?? (groups.some((g) => g.group_id === wantedGroup) ? wantedGroup : "");
  const [selected, setSelected] = useState<GameId | null>(null);
  // null until edited: the form shows your saved default for that game
  // (Settings → Default rules), else the standard one — and since the
  // profile may land after the first render, that's worked out on each
  // render rather than frozen into the initial state.
  const profile = useMe();
  const symbol = useCurrencySymbol();
  const savedTaidi = profile?.preferences.default_rules.taidi ?? null;
  const savedMahjong = profile?.preferences.default_rules.mahjong ?? null;
  const [taidiEdit, setTaidi] = useState<TaidiForm | null>(null);
  const [mahjongEdit, setMahjong] = useState<MahjongForm | null>(null);
  const taidi = useMemo(
    () => taidiEdit ?? taidiForm(savedTaidi ?? DEFAULT_RULES),
    [taidiEdit, savedTaidi],
  );
  const mahjong = useMemo(
    () => mahjongEdit ?? mahjongForm(savedMahjong ?? DEFAULT_MAHJONG_RULES),
    [mahjongEdit, savedMahjong],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [defaultNote, setDefaultNote] = useState<{ game: GameType; text: string; error: boolean } | null>(
    null,
  );

  useEffect(() => {
    // See the matching comment in room/[roomId]/page.tsx — must wait for
    // checked, or a genuinely signed-in user gets bounced before the
    // client-only auth read resolves.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    groupsApi
      .list()
      .then((r) => !cancelled && setGroups(r.groups))
      .catch(() => {
        /* no selector beats a broken page — the game can still be one-off */
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const taidiCheck = useMemo(() => checkTaidi(taidi), [taidi]);
  const mahjongCheck = useMemo(() => checkMahjong(mahjong), [mahjong]);

  function setT<K extends keyof TaidiForm>(key: K, value: TaidiForm[K]) {
    setTaidi((f) => ({ ...(f ?? taidi), [key]: value }));
  }

  function setM<K extends keyof MahjongForm>(key: K, value: MahjongForm[K]) {
    setMahjong((f) => ({ ...(f ?? mahjong), [key]: value }));
  }

  function setTaiRow(tai: number, field: "hu" | "zimo", value: string) {
    setMahjong((prev) => {
      const f = prev ?? mahjong;
      return {
        ...f,
        table: { ...f.table, [tai]: { ...(f.table[tai] ?? { hu: "0", zimo: "0" }), [field]: value } },
      };
    });
  }

  function setMaxTai(newMax: number) {
    setMahjong((prev) => {
      const f = prev ?? mahjong;
      const table = { ...f.table };
      for (let t = f.maxTai + 1; t <= newMax; t++) {
        table[t] = table[t] ?? { hu: "0", zimo: "0" };
      }
      return { ...f, maxTai: newMax, table };
    });
  }

  /** Saves the form as you have it now as this game's starting point. */
  async function saveDefault(gameType: GameType) {
    const rules = gameType === "mahjong" ? mahjongCheck.rules : taidiCheck.rules;
    if (!rules) return;
    setDefaultNote(null);
    try {
      setMe(await profileApi.setPreferences({ default_rules: { [gameType]: rules } }));
      setDefaultNote({ game: gameType, text: "Saved as your default.", error: false });
    } catch (e) {
      setDefaultNote({
        game: gameType,
        text: e instanceof ApiError ? e.message : "Couldn't save your default.",
        error: true,
      });
    }
  }

  async function handleCreate(gameType: GameType) {
    const rules = gameType === "mahjong" ? mahjongCheck.rules : taidiCheck.rules;
    if (!rules) return;
    setBusy(true);
    setError(null);
    let created: AnyRoomState;
    try {
      created = await api.createRoom(gameType, rules, chosenGroup || null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create a room.");
      setBusy(false);
      return;
    }
    // Deploy window: Vercel ships this page minutes before Render ships the
    // API, and an old API reads these cents as $0.50 chips (50x stakes). It
    // also echoes rules without cents_per_unit — so disband and bail.
    if (created.game_type === "mahjong" && !("cents_per_unit" in (created.draft_rules ?? {}))) {
      await mahjongApi.disband(created.room_id, created.seq).catch(() => {});
      setError("Update in progress — try again in a minute.");
      setBusy(false);
      return;
    }
    // POST /rooms already returned the full room — hand it to the room page
    // so it can render without waiting on a fetch that would tell it exactly
    // what we already know.
    stashFreshState(created);
    router.push(`/room/${created.room_id}?g=${gameType}`);
  }

  if (!user) return null;

  const me = mahjongCheck.errors;
  const te = taidiCheck.errors;

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => (selected ? setSelected(null) : router.push("/"))}
          data-testid="back-btn"
          aria-label="Back"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">New Room</h1>
      </div>

      <GroupSelect groups={groups} value={chosenGroup} onChange={setGroupId} />

      {!selected ? (
        <div className="space-y-3">
          {GAMES.map((g) => (
            <button
              key={g.id}
              onClick={() => setSelected(g.id)}
              data-testid={`game-tile-${g.id}`}
              className="w-full rounded-xl border border-border bg-surface px-4 py-4 text-left"
            >
              <p className="font-semibold">{g.label}</p>
              {!g.available && <p className="text-xs text-muted mt-0.5">Coming soon</p>}
            </button>
          ))}
        </div>
      ) : selected === "poker" ? (
        <div className="space-y-4 text-center py-8">
          <p data-testid="not-available" className="text-sm text-muted">
            Feature not available yet.
          </p>
          <button onClick={() => setSelected(null)} className="text-sm font-semibold text-brand">
            Choose another game
          </button>
        </div>
      ) : selected === "mahjong" ? (
        <div className="space-y-5">
          <div>
            <p className="text-xs text-muted mb-2">Presets</p>
            <div className="grid grid-cols-3 gap-2">
              {MAHJONG_PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setMahjong(mahjongForm(p.rules))}
                  data-testid={`mahjong-preset-${p.label.toLowerCase().replace(/\s+/g, "-")}`}
                  className="min-h-11 rounded-xl border border-border bg-surface px-2 py-2 text-xs font-semibold"
                >
                  {p.label}
                </button>
              ))}
              {savedMahjong && (
                <button
                  onClick={() => setMahjong(mahjongForm(savedMahjong))}
                  data-testid="mahjong-preset-mine"
                  className="min-h-11 rounded-xl border border-brand-strong bg-surface px-2 py-2 text-xs font-semibold text-brand"
                >
                  My default
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label={`咬 YAO (${symbol})`} error={me.yao}>
              <NumberInput
                decimal
                testId="rule-yao"
                value={mahjong.yao}
                error={me.yao}
                onChange={(v) => setM("yao", v)}
              />
            </Field>
            <Field label={`槓 GANG (${symbol})`} error={me.gang}>
              <NumberInput
                decimal
                testId="rule-gang"
                value={mahjong.gang}
                error={me.gang}
                onChange={(v) => setM("gang", v)}
              />
            </Field>
            <Field label={`Zimo bonus (${symbol})`} error={me.zimoBonus}>
              <NumberInput
                decimal
                testId="rule-zimo-bonus"
                value={mahjong.zimoBonus}
                error={me.zimoBonus}
                onChange={(v) => setM("zimoBonus", v)}
              />
            </Field>
            <Field label={`KLPPDD (${symbol})`} error={me.klppdd}>
              <NumberInput
                decimal
                testId="rule-klppdd"
                value={mahjong.klppdd}
                error={me.klppdd}
                onChange={(v) => setM("klppdd", v)}
              />
            </Field>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-muted">台 TAI payouts ({symbol})</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setMaxTai(Math.max(1, mahjong.maxTai - 1))}
                  disabled={mahjong.maxTai <= 1}
                  data-testid="tai-row-remove"
                  aria-label="Remove a tai level"
                  className="h-11 w-11 rounded-full border border-border text-base font-bold text-brand disabled:opacity-30"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => setMaxTai(Math.min(MAX_TAI_LIMIT, mahjong.maxTai + 1))}
                  disabled={mahjong.maxTai >= MAX_TAI_LIMIT}
                  data-testid="tai-row-add"
                  aria-label="Add a tai level"
                  className="h-11 w-11 rounded-full border border-border text-base font-bold text-brand disabled:opacity-30"
                >
                  +
                </button>
              </div>
            </div>
            <div className="grid grid-cols-[2.5rem_minmax(0,1fr)_minmax(0,1fr)] gap-2 items-center px-1 mb-1">
              <span />
              <span className="text-xs text-muted">Hu</span>
              <span className="text-xs text-muted">Zimo (each)</span>
            </div>
            <div className="space-y-2">
              {Array.from({ length: mahjong.maxTai }, (_, i) => i + 1).map((tai) => {
                const rowErr = me.rows[tai];
                return (
                  <div key={tai}>
                    <div className="grid grid-cols-[2.5rem_minmax(0,1fr)_minmax(0,1fr)] gap-2 items-center">
                      <span className="text-xs font-semibold text-brand">{tai}台</span>
                      <NumberInput
                        decimal
                        testId={`rule-tai-${tai}-hu`}
                        label={`${tai} tai hu`}
                        value={mahjong.table[tai]?.hu ?? ""}
                        error={rowErr?.hu}
                        onChange={(v) => setTaiRow(tai, "hu", v)}
                      />
                      <NumberInput
                        decimal
                        testId={`rule-tai-${tai}-zimo`}
                        label={`${tai} tai zimo`}
                        value={mahjong.table[tai]?.zimo ?? ""}
                        error={rowErr?.zimo}
                        onChange={(v) => setTaiRow(tai, "zimo", v)}
                      />
                    </div>
                    {(rowErr?.hu || rowErr?.zimo) && (
                      <p className="mt-0.5 pl-12 text-[11px] text-danger">{rowErr.hu ?? rowErr.zimo}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {error && <p className="text-sm text-center text-danger">{error}</p>}

          <button
            onClick={() => handleCreate("mahjong")}
            disabled={busy || !mahjongCheck.rules}
            data-testid="create-room-btn"
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
          >
            Create Room
          </button>
          <SaveDefault
            game="mahjong"
            disabled={!mahjongCheck.rules}
            note={defaultNote?.game === "mahjong" ? defaultNote : null}
            onSave={() => saveDefault("mahjong")}
          />
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Field label={`Value per card (${symbol})`} error={te.cardValue}>
              <NumberInput
                decimal
                testId="rule-card-value"
                value={taidi.cardValue}
                error={te.cardValue}
                onChange={(v) => setT("cardValue", v)}
              />
            </Field>
            <Field label="Base cards to winner" error={te.baseCards}>
              <NumberInput
                testId="rule-base-cards"
                value={taidi.baseCards}
                error={te.baseCards}
                onChange={(v) => setT("baseCards", v)}
              />
            </Field>
          </div>

          <Toggle
            label="Double / triple penalties"
            checked={taidi.multipliers}
            onChange={(v) => setT("multipliers", v)}
          />
          {taidi.multipliers && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="×2 at ≥" error={te.double}>
                <NumberInput
                  testId="rule-double"
                  value={taidi.double}
                  error={te.double}
                  onChange={(v) => setT("double", v)}
                />
              </Field>
              <Field label="×3 at ≥" error={te.triple}>
                <NumberInput
                  testId="rule-triple"
                  value={taidi.triple}
                  error={te.triple}
                  onChange={(v) => setT("triple", v)}
                />
              </Field>
            </div>
          )}

          <Toggle
            label="Difference payouts between losers"
            checked={taidi.difference}
            onChange={(v) => setT("difference", v)}
          />

          <Toggle
            label="Special hands"
            checked={taidi.specials}
            onChange={(v) => setT("specials", v)}
          />
          {taidi.specials && (
            <Field label="Cards per special hand" error={te.specialCards}>
              <NumberInput
                testId="rule-special-cards"
                value={taidi.specialCards}
                error={te.specialCards}
                onChange={(v) => setT("specialCards", v)}
              />
            </Field>
          )}

          {error && <p className="text-sm text-center text-danger">{error}</p>}

          <button
            onClick={() => handleCreate("taidi")}
            disabled={busy || !taidiCheck.rules}
            data-testid="create-room-btn"
            className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
          >
            Create Room
          </button>
          <SaveDefault
            game="taidi"
            disabled={!taidiCheck.rules}
            note={defaultNote?.game === "taidi" ? defaultNote : null}
            onSave={() => saveDefault("taidi")}
          />
        </div>
      )}
    </main>
  );
}
