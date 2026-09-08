"""Lifetime and round-level player statistics, derived from a list of ended rooms."""

from __future__ import annotations

from uuid import UUID

from .models import PlayerStats, RoomState, RoomStatus, RoundPhase, TaidiPlayerStats


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


def taidi_round_stats(rooms: list[RoomState]) -> dict[UUID, TaidiPlayerStats]:
    """Round-level stats per player across every ENDED room. See
    TaidiPlayerStats' docstring for the exact definitions (RESOLVED-only
    filtering, payer_rounds as the double/triple denominator)."""
    lifetime = player_lifetime_stats(rooms)
    stats: dict[UUID, TaidiPlayerStats] = {}

    def _get(pid: UUID, display_name: str) -> TaidiPlayerStats:
        s = stats.get(pid)
        if s is None:
            base = lifetime.get(pid) or PlayerStats(player_id=pid, display_name=display_name)
            s = TaidiPlayerStats(player_id=pid, display_name=display_name, lifetime=base)
            stats[pid] = s
        s.display_name = display_name
        return s

    for room in rooms:
        if room.status != RoomStatus.ENDED:
            continue
        for round_ in room.rounds:
            # Special hands settle immediately and independently of round
            # resolution — tally them regardless of the round's phase.
            for pid, count in round_.special_counts.items():
                if not count:
                    continue
                member = room.members.get(pid)
                s = _get(pid, member.display_name if member else str(pid))
                s.special_hands_claimed += count

            if round_.phase != RoundPhase.RESOLVED or round_.rules_snapshot is None:
                continue

            net_this_round: dict[UUID, int] = {}
            for t in round_.transfers:
                net_this_round[t.from_player] = (
                    net_this_round.get(t.from_player, 0) - t.amount_cents
                )
                net_this_round[t.to_player] = net_this_round.get(t.to_player, 0) + t.amount_cents

            # Membership is frozen for the whole IN_PROGRESS duration (join/
            # leave both require LOBBY), so every current member of an ended
            # room played every one of its resolved rounds.
            for pid, member in room.members.items():
                s = _get(pid, member.display_name)
                s.rounds_played += 1

                if round_.winner == pid:
                    s.round_wins += 1
                else:
                    s.payer_rounds += 1
                    cards = round_.cards_submitted.get(pid)
                    if cards is not None:
                        mult = round_.rules_snapshot.multiplier(cards)
                        if mult == 3:
                            s.triple_rounds += 1
                        elif mult == 2:
                            s.double_rounds += 1

                net = net_this_round.get(pid, 0)
                if net > 0:
                    s.profit_rounds += 1
                if s.best_round_cents is None or net > s.best_round_cents:
                    s.best_round_cents = net
                if s.worst_round_cents is None or net < s.worst_round_cents:
                    s.worst_round_cents = net

    for s in stats.values():
        s.round_win_rate = s.round_wins / s.rounds_played if s.rounds_played else 0.0
        s.profit_rate = s.profit_rounds / s.rounds_played if s.rounds_played else 0.0
        s.double_rate = s.double_rounds / s.payer_rounds if s.payer_rounds else 0.0
        s.triple_rate = s.triple_rounds / s.payer_rounds if s.payer_rounds else 0.0

    return stats
