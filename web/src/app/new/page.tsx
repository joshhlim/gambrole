"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import type { GameRules, GameType } from "@/lib/types";
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
  "w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand-strong";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-xs text-muted mb-1">{label}</span>
      {children}
    </label>
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

export default function NewRoomPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [selected, setSelected] = useState<GameId | null>(null);
  const [rules, setRules] = useState<GameRules>(DEFAULT_RULES);
  const [mahjongRules, setMahjongRules] = useState<MahjongRules>(DEFAULT_MAHJONG_RULES);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // See the matching comment in room/[roomId]/page.tsx — must wait for
    // checked, or a genuinely signed-in user gets bounced before the
    // client-only auth read resolves.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  function set<K extends keyof GameRules>(key: K, value: GameRules[K]) {
    setRules((r) => ({ ...r, [key]: value }));
  }

  function setMahjong<K extends keyof MahjongRules>(key: K, value: MahjongRules[K]) {
    setMahjongRules((r) => ({ ...r, [key]: value }));
  }

  function setTaiRow(tai: number, field: keyof TaiPayout, value: number) {
    setMahjongRules((r) => ({
      ...r,
      tai_table: {
        ...r.tai_table,
        [tai]: { ...(r.tai_table[tai] ?? { hu: 0, zimo: 0 }), [field]: value },
      },
    }));
  }

  function setMaxTai(newMax: number) {
    setMahjongRules((r) => {
      const table = { ...r.tai_table };
      for (let t = r.max_tai + 1; t <= newMax; t++) {
        table[t] = table[t] ?? { hu: 0, zimo: 0 };
      }
      return { ...r, max_tai: newMax, tai_table: table };
    });
  }

  async function handleCreate(gameType: GameType) {
    setBusy(true);
    setError(null);
    try {
      // The room only takes rules at start_game time (once the lobby is
      // full), so we hold onto what was configured here until then.
      const created = await api.createRoom(gameType);
      const chosenRules = gameType === "mahjong" ? mahjongRules : rules;
      sessionStorage.setItem(`gambrole_rules_${created.room_id}`, JSON.stringify(chosenRules));
      // POST /rooms already returned the full room — hand it to the room
      // page so it can render without waiting on a fetch that would tell it
      // exactly what we already know. Stamped so a stale one is ignored.
      sessionStorage.setItem(
        `gambrole_state_${created.room_id}`,
        JSON.stringify({ at: Date.now(), state: created }),
      );
      router.push(`/room/${created.room_id}?g=${gameType}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't create a room.");
      setBusy(false);
    }
  }

  if (!user) return null;

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => (selected ? setSelected(null) : router.push("/"))}
          data-testid="back-btn"
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
                  onClick={() => setMahjongRules(p.rules)}
                  data-testid={`mahjong-preset-${p.label.toLowerCase().replace(/\s+/g, "-")}`}
                  className="rounded-xl border border-border bg-surface px-2 py-2 text-xs font-semibold"
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Field label="Base chips">
              <input
                type="number"
                min={0}
                data-testid="rule-base"
                value={mahjongRules.base_chips}
                onChange={(e) => setMahjong("base_chips", Math.max(0, Number(e.target.value) || 0))}
                className={inputCls}
              />
            </Field>
            <Field label="咬 YAO">
              <input
                type="number"
                min={0}
                data-testid="rule-yao"
                value={mahjongRules.yao_chips}
                onChange={(e) => setMahjong("yao_chips", Math.max(0, Number(e.target.value) || 0))}
                className={inputCls}
              />
            </Field>
            <Field label="槓 GANG">
              <input
                type="number"
                min={0}
                data-testid="rule-gang"
                value={mahjongRules.gang_chips}
                onChange={(e) => setMahjong("gang_chips", Math.max(0, Number(e.target.value) || 0))}
                className={inputCls}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Zimo bonus (optional)">
              <input
                type="number"
                min={0}
                data-testid="rule-zimo-bonus"
                value={mahjongRules.zimo_bonus_chips}
                onChange={(e) =>
                  setMahjong("zimo_bonus_chips", Math.max(0, Number(e.target.value) || 0))
                }
                className={inputCls}
              />
            </Field>
            <Field label="KLPPDD (optional)">
              <input
                type="number"
                min={0}
                data-testid="rule-klppdd"
                value={mahjongRules.klppdd_chips}
                onChange={(e) => setMahjong("klppdd_chips", Math.max(0, Number(e.target.value) || 0))}
                className={inputCls}
              />
            </Field>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-muted">台 TAI payouts (chips)</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setMaxTai(Math.max(1, mahjongRules.max_tai - 1))}
                  disabled={mahjongRules.max_tai <= 1}
                  data-testid="tai-row-remove"
                  className="h-7 w-7 rounded-full border border-border text-sm font-bold text-brand disabled:opacity-30"
                >
                  −
                </button>
                <button
                  type="button"
                  onClick={() => setMaxTai(mahjongRules.max_tai + 1)}
                  data-testid="tai-row-add"
                  className="h-7 w-7 rounded-full border border-border text-sm font-bold text-brand"
                >
                  +
                </button>
              </div>
            </div>
            <div className="grid grid-cols-[2.5rem_1fr_1fr] gap-2 items-center px-1 mb-1">
              <span />
              <span className="text-xs text-muted">Hu</span>
              <span className="text-xs text-muted">Zimo (each)</span>
            </div>
            <div className="space-y-2">
              {Array.from({ length: mahjongRules.max_tai }, (_, i) => i + 1).map((tai) => (
                <div key={tai} className="grid grid-cols-[2.5rem_1fr_1fr] gap-2 items-center">
                  <span className="text-xs font-semibold text-brand">{tai}台</span>
                  <input
                    type="number"
                    min={0}
                    data-testid={`rule-tai-${tai}-hu`}
                    value={mahjongRules.tai_table[tai]?.hu ?? 0}
                    onChange={(e) => setTaiRow(tai, "hu", Math.max(0, Number(e.target.value) || 0))}
                    className={inputCls}
                  />
                  <input
                    type="number"
                    min={0}
                    data-testid={`rule-tai-${tai}-zimo`}
                    value={mahjongRules.tai_table[tai]?.zimo ?? 0}
                    onChange={(e) => setTaiRow(tai, "zimo", Math.max(0, Number(e.target.value) || 0))}
                    className={inputCls}
                  />
                </div>
              ))}
            </div>
          </div>

          {error && <p className="text-sm text-center text-danger">{error}</p>}

          <button
            onClick={() => handleCreate("mahjong")}
            disabled={busy}
            data-testid="create-room-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Create Room
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Value per card ($)">
              <input
                type="number"
                step={0.05}
                min={0}
                data-testid="rule-card-value"
                value={rules.card_value_cents / 100}
                onChange={(e) => set("card_value_cents", Math.round((Number(e.target.value) || 0) * 100))}
                className={inputCls}
              />
            </Field>
            <Field label="Base cards to winner">
              <input
                type="number"
                min={0}
                value={rules.base_cards}
                onChange={(e) => set("base_cards", Number(e.target.value) || 0)}
                className={inputCls}
              />
            </Field>
          </div>

          <Toggle
            label="Double / triple penalties"
            checked={rules.multipliers_enabled}
            onChange={(v) => set("multipliers_enabled", v)}
          />
          {rules.multipliers_enabled && (
            <div className="grid grid-cols-2 gap-3">
              <Field label="×2 at ≥">
                <input
                  type="number"
                  min={1}
                  value={rules.double_threshold}
                  onChange={(e) => set("double_threshold", Number(e.target.value) || 1)}
                  className={inputCls}
                />
              </Field>
              <Field label="×3 at ≥">
                <input
                  type="number"
                  min={1}
                  value={rules.triple_threshold}
                  onChange={(e) => set("triple_threshold", Number(e.target.value) || 1)}
                  className={inputCls}
                />
              </Field>
            </div>
          )}

          <Toggle
            label="Difference payouts between losers"
            checked={rules.difference_payouts}
            onChange={(v) => set("difference_payouts", v)}
          />

          <Toggle
            label="Special hands"
            checked={rules.special_hands_enabled}
            onChange={(v) => set("special_hands_enabled", v)}
          />
          {rules.special_hands_enabled && (
            <Field label="Cards per special hand">
              <input
                type="number"
                min={1}
                value={rules.special_hand_cards}
                onChange={(e) => set("special_hand_cards", Number(e.target.value) || 1)}
                className={inputCls}
              />
            </Field>
          )}

          {error && <p className="text-sm text-center text-danger">{error}</p>}

          <button
            onClick={() => handleCreate("taidi")}
            disabled={busy}
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
