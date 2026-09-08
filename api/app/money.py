"""Display-layer currency conversion, shared by stats_service.py and
events_store.py (which can't import from stats_service without a cycle,
since stats_service already imports from events_store).

1 Mahjong chip = $0.50. Lives here rather than in mahjong_core (which is
currency-agnostic domain logic) or mahjong_core's stats module (which stays
chip-denominated) — see ADR-0007.
"""

from __future__ import annotations

MAHJONG_CHIP_VALUE_CENTS = 50
