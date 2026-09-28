"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
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

// "3/6 半" — a real Hong Kong-style stakes table. Money is chips, not
// dollars; the tai payouts are non-linear (a 5-tai hand pays far more than
// 5x a 1-tai hand), so this is a lookup table rather than a per-tai rate.
const BAN_3_6_TABLE: Record<string, TaiPayout> = {
  1: { hu: 4, zimo: 4 },
  2: { hu: 7, zimo: 5 },
  3: { hu: 11, zimo: 7 },
  4: { hu: 20, zimo: 12 },
  5: { hu: 40, zimo: 22 },
};

const DEFAULT_MAHJONG_RULES: MahjongRules = {
  base_chips: 300,
  yao_chips: 2,
  gang_chips: 2,
  zimo_bonus_chips: 0,
  klppdd_chips: 0,
  max_tai: 5,
  tai_table: BAN_3_6_TABLE,
};

// "5/1 半" — higher stakes, more tai levels. Same non-linear-table shape
// as "3/6 半", plus a zimo bonus and KLPPDD on by default.
const BAN_5_1_TABLE: Record<string, TaiPayout> = {
  1: { hu: 4, zimo: 2 },
  2: { hu: 8, zimo: 4 },
  3: { hu: 16, zimo: 8 },
  4: { hu: 32, zimo: 16 },
  5: { hu: 64, zimo: 32 },
  6: { hu: 128, zimo: 64 },
  7: { hu: 256, zimo: 128 },
};

const HIGH_STAKES_MAHJONG_RULES: MahjongRules = {
  base_chips: 500,
  yao_chips: 3,
  gang_chips: 3,
  zimo_bonus_chips: 5,
  klppdd_chips: 5,
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

/** Dollars in, cents out: at most two decimals, $0–$100. */
function dollarsToCents(raw: string): Check {
  const t = raw.trim();
  if (t === "") return { value: null, error: "Required" };
  if (!/^\d*(\.\d{0,2})?$/.test(t) || t === ".") return { value: null, error: "e.g. 0.20" };
  const cents = Math.round(Number(t) * 100);
  if (cents > 10000) return { value: null, error: "Max $100.00" };
  return { value: cents, error: null };
}

const str = (n: number) => String(n);

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

const TAIDI_FORM: TaidiForm = {
  cardValue: (DEFAULT_RULES.card_value_cents / 100).toFixed(2),
  baseCards: str(DEFAULT_RULES.base_cards),
  multipliers: DEFAULT_RULES.multipliers_enabled,
  double: str(DEFAULT_RULES.double_threshold),
  triple: str(DEFAULT_RULES.triple_threshold),
  difference: DEFAULT_RULES.difference_payouts,
  specials: DEFAULT_RULES.special_hands_enabled,
  specialCards: str(DEFAULT_RULES.special_hand_cards),
};

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

const MAX_TAI_LIMIT = 20;

interface MahjongForm {
  base: string;
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
    table[tai] = { hu: str(p.hu), zimo: str(p.zimo) };
  }
  return {
    base: str(r.base_chips),
    yao: str(r.yao_chips),
    gang: str(r.gang_chips),
    zimoBonus: str(r.zimo_bonus_chips),
    klppdd: str(r.klppdd_chips),
    maxTai: r.max_tai,
    table,
  };
}

function checkMahjong(f: MahjongForm) {
  const base = wholeNumber(f.base, 0, 1_000_000);
  const yao = wholeNumber(f.yao, 0, 100_000);
  const gang = wholeNumber(f.gang, 0, 100_000);
  const zimoBonus = wholeNumber(f.zimoBonus, 0, 100_000);
  const klppdd = wholeNumber(f.klppdd, 0, 100_000);
  const rows: Record<string, { hu: Check; zimo: Check }> = {};
  for (let t = 1; t <= f.maxTai; t++) {
    const row = f.table[t] ?? { hu: "", zimo: "" };
    rows[t] = { hu: wholeNumber(row.hu, 0, 1_000_000), zimo: wholeNumber(row.zimo, 0, 1_000_000) };
  }
  const all = [base, yao, gang, zimoBonus, klppdd, ...Object.values(rows).flatMap((r) => [r.hu, r.zimo])];
  const valid = all.every((c) => c.error === null);
  const rules: MahjongRules | null = valid
    ? {
        base_chips: base.value!,
        yao_chips: yao.value!,
        gang_chips: gang.value!,
        zimo_bonus_chips: zimoBonus.value!,
        klppdd_chips: klppdd.value!,
        max_tai: f.maxTai,
        tai_table: Object.fromEntries(
          Object.entries(rows).map(([t, r]) => [t, { hu: r.hu.value!, zimo: r.zimo.value! }]),
        ),
      }
    : null;
  return {
    errors: {
      base: base.error,
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

export default function NewRoomPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [selected, setSelected] = useState<GameId | null>(null);
  const [taidi, setTaidi] = useState<TaidiForm>(TAIDI_FORM);
  const [mahjong, setMahjong] = useState<MahjongForm>(() => mahjongForm(DEFAULT_MAHJONG_RULES));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // See the matching comment in room/[roomId]/page.tsx — must wait for
    // checked, or a genuinely signed-in user gets bounced before the
    // client-only auth read resolves.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  const taidiCheck = useMemo(() => checkTaidi(taidi), [taidi]);
  const mahjongCheck = useMemo(() => checkMahjong(mahjong), [mahjong]);

  function setT<K extends keyof TaidiForm>(key: K, value: TaidiForm[K]) {
    setTaidi((f) => ({ ...f, [key]: value }));
  }

  function setM<K extends keyof MahjongForm>(key: K, value: MahjongForm[K]) {
    setMahjong((f) => ({ ...f, [key]: value }));
  }

  function setTaiRow(tai: number, field: "hu" | "zimo", value: string) {
    setMahjong((f) => ({
      ...f,
      table: { ...f.table, [tai]: { ...(f.table[tai] ?? { hu: "0", zimo: "0" }), [field]: value } },
    }));
  }

  function setMaxTai(newMax: number) {
    setMahjong((f) => {
      const table = { ...f.table };
      for (let t = f.maxTai + 1; t <= newMax; t++) {
        table[t] = table[t] ?? { hu: "0", zimo: "0" };
      }
      return { ...f, maxTai: newMax, table };
    });
  }

  async function handleCreate(gameType: GameType) {
    const rules = gameType === "mahjong" ? mahjongCheck.rules : taidiCheck.rules;
    if (!rules) return;
    setBusy(true);
    setError(null);
    let created: AnyRoomState;
    try {
      created = await api.createRoom(gameType, rules);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create a room.");
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
                  className="rounded-xl border border-border bg-surface px-2 py-2 text-xs font-semibold"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Field label="Base chips" error={me.base}>
              <NumberInput testId="rule-base" value={mahjong.base} error={me.base} onChange={(v) => setM("base", v)} />
            </Field>
            <Field label="咬 YAO" error={me.yao}>
              <NumberInput testId="rule-yao" value={mahjong.yao} error={me.yao} onChange={(v) => setM("yao", v)} />
            </Field>
            <Field label="槓 GANG" error={me.gang}>
              <NumberInput testId="rule-gang" value={mahjong.gang} error={me.gang} onChange={(v) => setM("gang", v)} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Zimo bonus (optional)" error={me.zimoBonus}>
              <NumberInput
                testId="rule-zimo-bonus"
                value={mahjong.zimoBonus}
                error={me.zimoBonus}
                onChange={(v) => setM("zimoBonus", v)}
              />
            </Field>
            <Field label="KLPPDD (optional)" error={me.klppdd}>
              <NumberInput
                testId="rule-klppdd"
                value={mahjong.klppdd}
                error={me.klppdd}
                onChange={(v) => setM("klppdd", v)}
              />
            </Field>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-muted">台 TAI payouts (chips)</p>
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
                        testId={`rule-tai-${tai}-hu`}
                        label={`${tai} tai hu`}
                        value={mahjong.table[tai]?.hu ?? ""}
                        error={rowErr?.hu}
                        onChange={(v) => setTaiRow(tai, "hu", v)}
                      />
                      <NumberInput
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
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Create Room
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Value per card ($)" error={te.cardValue}>
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
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Create Room
          </button>
        </div>
      )}
    </main>
  );
}
