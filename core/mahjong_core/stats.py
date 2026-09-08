"""Lifetime player statistics, derived from a list of ended Mahjong rooms.

Mirrors taidi_core.stats.player_lifetime_stats exactly (same read-only
access pattern: .status/.balances/.members/.ended_at) but typed against
mahjong_core's own RoomState — see ADR-0006 for why this isn't shared
directly (mypy strict would reject passing MahjongRoomState where
taidi_core.RoomState is expected, even though the logic is identical).
"""

from __future__ import annotations

from uuid import UUID

from taidi_core.models import PlayerStats, RoomStatus

from .models import MahjongPlayerStats, RoomState


def player_lifetime_stats(rooms: list[RoomState]) -> dict[UUID, PlayerStats]:
    """Lifetime stats per player across every ENDED room. Non-ended rooms are ignored."""
    stats: dict[UUID, PlayerStats] = {}
    for room in rooms:
        if room.status != RoomStatus.ENDED:
            continue
        for pid, balance in room.balances.items():
            member = room.members.get(pid)
            name = member.display_name if member else str(pid)
            s = stats.get(pid)
            if s is None:
                s = PlayerStats(player_id=pid, display_name=name)
                stats[pid] = s
            s.display_name = name
            s.games += 1
            s.total_cents += balance
            if balance > 0:
                s.wins += 1
            elif balance < 0:
                s.losses += 1
            else:
                s.ties += 1
            if room.ended_at and (s.last_played is None or room.ended_at > s.last_played):
                s.last_played = room.ended_at
    return stats


def mahjong_hand_stats(rooms: list[RoomState]) -> dict[UUID, MahjongPlayerStats]:
    """Hand-level stats per player across every ENDED room. See
    MahjongPlayerStats' docstring for the exact definitions (closed-hands-
    only filtering, dealer identity via Member.seat)."""
    lifetime = player_lifetime_stats(rooms)
    stats: dict[UUID, MahjongPlayerStats] = {}

    def _get(pid: UUID, display_name: str) -> MahjongPlayerStats:
        s = stats.get(pid)
        if s is None:
            base = lifetime.get(pid) or PlayerStats(player_id=pid, display_name=display_name)
            s = MahjongPlayerStats(player_id=pid, display_name=display_name, lifetime=base)
            stats[pid] = s
        s.display_name = display_name
        return s

    for room in rooms:
        if room.status != RoomStatus.ENDED:
            continue
        for hand in room.hands:
            if not hand.closed:
                continue

            net_this_hand: dict[UUID, int] = {}
            for t in hand.transfers:
                net_this_hand[t.from_player] = net_this_hand.get(t.from_player, 0) - t.amount_cents
                net_this_hand[t.to_player] = net_this_hand.get(t.to_player, 0) + t.amount_cents
                for pid, sign in ((t.from_player, -1), (t.to_player, 1)):
                    member = room.members.get(pid)
                    if member is None:
                        continue
                    s = _get(pid, member.display_name)
                    s.profit_by_kind[t.kind.value] = (
                        s.profit_by_kind.get(t.kind.value, 0) + sign * t.amount_cents
                    )

            for pid, member in room.members.items():
                s = _get(pid, member.display_name)
                s.hands_played += 1

                is_dealer = member.seat == hand.dealer_seat
                if is_dealer:
                    s.dealer_hands += 1

                if hand.winner == pid:
                    s.hu_count += 1
                    if is_dealer:
                        s.dealer_wins += 1
                    if hand.mode:
                        s.win_mode_counts[hand.mode] = s.win_mode_counts.get(hand.mode, 0) + 1
                    if hand.tai is not None:
                        s.tai_distribution[hand.tai] = s.tai_distribution.get(hand.tai, 0) + 1

                net = net_this_hand.get(pid, 0)
                if s.best_hand_chips is None or net > s.best_hand_chips:
                    s.best_hand_chips = net
                if s.worst_hand_chips is None or net < s.worst_hand_chips:
                    s.worst_hand_chips = net

    for s in stats.values():
        s.hu_rate = s.hu_count / s.hands_played if s.hands_played else 0.0
        s.dealer_win_rate = s.dealer_wins / s.dealer_hands if s.dealer_hands else 0.0
        s.win_mode_rates = (
            {mode: count / s.hu_count for mode, count in s.win_mode_counts.items()}
            if s.hu_count
            else {}
        )
        wins_with_tai = sum(s.tai_distribution.values())
        total_tai = sum(tai * count for tai, count in s.tai_distribution.items())
        s.avg_tai_on_wins = total_tai / wins_with_tai if wins_with_tai else 0.0

    return stats
