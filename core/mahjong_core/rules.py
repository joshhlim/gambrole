"""Pure money-math for YAO, GANG, and HU declarations.

No state, no player resolution — machine.py owns "who pays whom" (it needs
RoomState to resolve seats to players anyway); this module only answers
"how much", so it's trivial to golden-fixture test in isolation. Amounts are
in the rules' units (see MahjongRules.cents_per_unit; machine.apply turns
them into cents) — real mahjong stakes tables are non-linear by tai, hence
`rules.tai_table` lookup rather than a rate multiplied by tai. See
ADR-0006 and the plan's settlement table for the source of these formulas.
"""

from __future__ import annotations

from .models import MahjongRules

ENGINE_VERSION = "mahjong-3"


def yao_amount(rules: MahjongRules, an: bool) -> int:
    return rules.yao_amount * (2 if an else 1)


def gang_amount_self(rules: MahjongRules) -> int:
    return rules.gang_amount


def gang_amount_other(rules: MahjongRules) -> int:
    return rules.gang_amount * 3


def gang_amount_angang(rules: MahjongRules) -> int:
    return rules.gang_amount * 2


def hu_amount_direct(rules: MahjongRules, tai: int) -> int:
    return rules.tai_table[tai].hu


def hu_amount_zimo_each(rules: MahjongRules, tai: int) -> int:
    return rules.tai_table[tai].zimo


def hu_amount_bao(rules: MahjongRules, tai: int) -> int:
    return rules.tai_table[tai].zimo * 3


def zimo_bonus_amount(rules: MahjongRules) -> int:
    return rules.zimo_bonus_amount


def klppdd_amount_each(rules: MahjongRules) -> int:
    return rules.klppdd_amount


def klppdd_amount_single_payer(rules: MahjongRules) -> int:
    return rules.klppdd_amount * 3
