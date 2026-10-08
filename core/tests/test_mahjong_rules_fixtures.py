"""Golden fixtures for MahjongRules' default tai_table — the "3/6 半"
preset. Hand-copied from the stakes table the product owner gave (in $0.50
chips: 4/7/11/20/40 hu, 4/5/7/12/22 zimo, yao and gang 2), so this test
would catch an accidental edit to the defaults, not just a broken lookup
mechanism (that's what test_mahjong_engine_properties.py covers)."""

from __future__ import annotations

from mahjong_core.models import LEGACY_CENTS_PER_CHIP, MahjongRules

CHIPS = {
    1: (4, 4),
    2: (7, 5),
    3: (11, 7),
    4: (20, 12),
    5: (40, 22),
}


def test_default_rules_are_the_3_6_ban_preset_in_cents():
    rules = MahjongRules()
    assert rules.cents_per_unit == 1
    assert rules.yao_amount == 2 * LEGACY_CENTS_PER_CHIP
    assert rules.gang_amount == 2 * LEGACY_CENTS_PER_CHIP
    assert rules.zimo_bonus_amount == 0
    assert rules.klppdd_amount == 0
    assert rules.max_tai == 5
    for tai, (hu, zimo) in CHIPS.items():
        assert rules.tai_table[tai].hu == hu * LEGACY_CENTS_PER_CHIP
        assert rules.tai_table[tai].zimo == zimo * LEGACY_CENTS_PER_CHIP


def test_stored_rules_from_before_dollars_read_as_chips():
    """A game started before amounts became dollars stored chip values under
    the old field names and no cents_per_unit."""
    rules = MahjongRules.from_stored({"base_chips": 300, "yao_chips": 2, "gang_chips": 2})
    assert rules.cents_per_unit == LEGACY_CENTS_PER_CHIP
    assert rules.yao_amount == 2
    assert "yao_amount" in rules.model_dump() and "yao_chips" not in rules.model_dump()


def test_new_style_rules_are_cents_even_without_cents_per_unit():
    assert MahjongRules.from_stored({"yao_amount": 100}).cents_per_unit == 1
    assert MahjongRules.from_stored({}).cents_per_unit == 1
