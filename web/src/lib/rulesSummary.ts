import { money } from "./format";
import { ruleCents, type MahjongRules } from "./mahjongTypes";
import type { GameRules } from "./types";

// Client-side twins of the backend's GameRules.describe() and
// MahjongRules.describe() — those aren't serialized, and one line is all a
// phone at the table has room for.

export function describeTaidiRules(r: GameRules): string {
  const parts = [`${money(r.card_value_cents)}/card`];
  if (r.base_cards) parts.push(`base ${r.base_cards}`);
  parts.push(
    r.multipliers_enabled
      ? `×2 at ${r.double_threshold}+, ×3 at ${r.triple_threshold}+`
      : "no multipliers",
  );
  parts.push(r.difference_payouts ? "difference payouts" : "winner-only");
  if (r.special_hands_enabled) parts.push(`special +${r.special_hand_cards}`);
  return parts.join(" · ");
}

export function describeMahjongRules(r: MahjongRules): string | null {
  // A lobby drafted before dollars still has its raw chip-named draft rules
  // (the server converts them when the game starts) — nothing to show yet.
  if (r.cents_per_unit === undefined) return null;
  const m = (amount: number) => money(ruleCents(r, amount));
  const top = r.tai_table[String(r.max_tai)];
  const parts = [
    `yao ${m(r.yao_amount)}`,
    `gang ${m(r.gang_amount)}`,
    `${r.max_tai} tai max${top ? ` (${m(top.hu)}/${m(top.zimo)})` : ""}`,
  ];
  if (r.zimo_bonus_amount) parts.push(`zimo bonus ${m(r.zimo_bonus_amount)}`);
  if (r.klppdd_amount) parts.push(`klppdd ${m(r.klppdd_amount)}`);
  return parts.join(" · ");
}
