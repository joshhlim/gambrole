"""The room/round state machine.

Two halves, kept deliberately separate so an API layer can persist an event
before applying it:

- command functions (`join_player`, `start_game`, `claim_win`, ...) are the
  *validate* step: given the current state, they either return the event(s)
  the command produces, or raise a MachineError. They never mutate state.
- `apply(state, event) -> state` is the single source of truth for how one
  event changes state. Replaying a room's whole event log through `apply`
  (via `fold`) must reproduce the same RoomState `dispatch`ing live would.

A command can produce more than one event: submitting the last outstanding
card count for a round also emits a system `round_resolved` event in the
same call, so callers always get a flat, already-ordered event list to
persist and apply.

Design notes:
- Every mutating command takes `expected_seq`; a mismatch raises SeqConflict
  so the caller can show "here's what actually happened" instead of merging.
- Nothing is ever deleted. Voiding a round resets it to `playing` rather than
  marking a terminal "voided" phase — the `round_voided` event itself is the
  permanent audit record; RoomState only ever reflects the current attempt.
- Special hands settle immediately (independent of the round they occur in);
  card-based transfers settle only when every loser's count is in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .errors import IllegalTransition, NotAuthorized, SeqConflict
from .models import (
    Event,
    EventType,
    GameRules,
    Member,
    RoomState,
    RoomStatus,
    RoundPhase,
    RoundState,
    Transfer,
    TransferKind,
)
from .rules import ENGINE_VERSION, compute_card_transfers, compute_special_transfer


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def _check_seq(state: RoomState, expected_seq: int) -> None:
    if expected_seq != state.seq:
        raise SeqConflict(expected=expected_seq, actual=state.seq)


def _mk_event(
    state: RoomState,
    type_: EventType,
    actor: UUID | None,
    payload: dict[str, Any],
    now: datetime,
    seq: int,
    event_id: UUID | None,
) -> Event:
    return Event(
        event_id=event_id or uuid4(),
        room_id=state.room_id,
        seq=seq,
        type=type_,
        actor=actor,
        payload=payload,
        created_at=now,
    )


def _require_in_progress(state: RoomState) -> None:
    if state.status != RoomStatus.IN_PROGRESS:
        raise IllegalTransition("The game hasn't started yet.")


def _require_member(state: RoomState, player_id: UUID) -> None:
    if player_id not in state.members:
        raise NotAuthorized("Not a member of this room.")


# ============================================================
# Commands (validate step): given state, return event(s) or raise.
# ============================================================


def join_player(
    state: RoomState,
    *,
    expected_seq: int,
    player_id: UUID,
    display_name: str,
    is_guest: bool = False,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Room already started — new players can't join mid-game.")
    if player_id in state.members:
        raise IllegalTransition("Player has already joined this room.")
    payload = {"player_id": str(player_id), "display_name": display_name, "is_guest": is_guest}
    return [
        _mk_event(
            state,
            EventType.PLAYER_JOINED,
            player_id,
            payload,
            _now(now),
            expected_seq + 1,
            event_id,
        )
    ]


def leave_room(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_member(state, actor)
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Can't leave once the game has started.")
    if actor == state.host_id:
        raise IllegalTransition("The host can't leave — disband the room instead.")
    payload = {"player_id": str(actor)}
    return [
        _mk_event(
            state, EventType.PLAYER_LEFT, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def step_out(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    """Walk away from a game that's already running.

    Distinct from `leave_room`, which is lobby-only and forgets you
    entirely: here you've played, so your balance stays on the table and
    settles with everyone else's at the end. You just take no part in
    further rounds.

    One-way by construction — `join_player` refuses once a game has
    started, so there is no path back into this game afterwards.

    Emits up to three events, because stepping out can make the current
    round unresolvable and can leave too few players to carry on:
    the round is voided if it was mid-collection, then the departure, then
    a game end if fewer than two players remain.
    """
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)

    events: list[Event] = []
    seq = expected_seq
    ts = _now(now)

    # A round waiting on card counts can't resolve without everyone who was
    # dealt in, so put it back to the start rather than stranding the table.
    round_ = state.current_round
    if round_ is not None and round_.phase == RoundPhase.COLLECTING:
        seq += 1
        events.append(
            _mk_event(
                state,
                EventType.ROUND_VOIDED,
                actor,
                {"round_no": round_.round_no},
                ts,
                seq,
                None,
            )
        )

    seq += 1
    events.append(
        _mk_event(
            state,
            EventType.PLAYER_STEPPED_OUT,
            actor,
            {"player_id": str(actor)},
            ts,
            seq,
            event_id,
        )
    )

    # Taidi needs two players. If this departure drops the table below that,
    # the game is over — settle it now rather than leaving a room nobody can
    # play or end.
    if len(state.members) - 1 < 2:
        seq += 1
        events.append(
            _mk_event(
                state, EventType.GAME_ENDED, actor, {"reason": "too_few_players"}, ts, seq, None
            )
        )
    return events


def disband_room(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can disband the room.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Can't disband once the game has started.")
    return [
        _mk_event(state, EventType.ROOM_DISBANDED, actor, {}, _now(now), expected_seq + 1, event_id)
    ]


def start_game(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    rules: GameRules,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can start the game.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Game already started.")
    if len(state.members) < 2:
        raise IllegalTransition("Need at least two players to start.")
    payload = {"rules": rules.model_dump(mode="json")}
    return [
        _mk_event(
            state, EventType.GAME_STARTED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def claim_win(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    round_ = state.current_round
    if round_ is None or round_.phase != RoundPhase.PLAYING:
        claimant = (
            state.members[round_.winner].display_name if round_ and round_.winner else "someone"
        )
        raise IllegalTransition(f"This round was already claimed by {claimant}.")
    payload = {"round_no": round_.round_no, "winner": str(actor)}
    return [
        _mk_event(
            state, EventType.WIN_CLAIMED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def _submit_cards_events(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    target: UUID,
    cards: int,
    event_type: EventType,
    now: datetime | None,
    event_id: UUID | None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    _require_member(state, target)
    round_ = state.current_round
    if round_ is None or round_.phase != RoundPhase.COLLECTING:
        raise IllegalTransition("No round is currently collecting cards.")
    if target == round_.winner:
        raise IllegalTransition("The winner doesn't submit a card count.")
    if target in round_.cards_submitted:
        raise IllegalTransition(
            f"{state.members[target].display_name} already submitted for this round."
        )
    # Zero is the winner's card count, and the engine identifies the winner
    # as "the one player holding none" — so a loser submitting 0 makes the
    # round unresolvable (rules.compute_card_transfers raises a bare
    # ValueError, which escapes the MachineError handling as a 500). Reject
    # it here, where it can be explained.
    if cards < 1:
        raise IllegalTransition(
            "A losing hand has at least 1 card left — only the winner finishes on 0."
        )

    ts = _now(now)
    payload = {"round_no": round_.round_no, "target_player": str(target), "cards": cards}
    submit_seq = expected_seq + 1
    events = [_mk_event(state, event_type, actor, payload, ts, submit_seq, event_id)]

    submitted_after = dict(round_.cards_submitted)
    submitted_after[target] = cards
    non_winner_ids = [p for p in state.member_ids if p != round_.winner]
    if all(p in submitted_after for p in non_winner_ids):
        assert state.rules is not None
        assert round_.winner is not None
        card_counts: dict[UUID, int] = {round_.winner: 0, **submitted_after}
        transfers, winner = compute_card_transfers(card_counts, state.rules, round_.round_no)
        resolve_payload = {
            "round_no": round_.round_no,
            "card_counts": {str(p): c for p, c in card_counts.items()},
            "transfers": [t.model_dump(mode="json") for t in transfers],
            "winner": str(winner),
            "engine_version": ENGINE_VERSION,
        }
        events.append(
            _mk_event(
                state, EventType.ROUND_RESOLVED, None, resolve_payload, ts, submit_seq + 1, None
            )
        )
    return events


def submit_cards(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    cards: int,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    return _submit_cards_events(
        state,
        expected_seq=expected_seq,
        actor=actor,
        target=actor,
        cards=cards,
        event_type=EventType.CARDS_SUBMITTED,
        now=now,
        event_id=event_id,
    )


def submit_for(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    target_player: UUID,
    cards: int,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    if actor != state.host_id:
        raise NotAuthorized("Only the host can submit on another player's behalf.")
    return _submit_cards_events(
        state,
        expected_seq=expected_seq,
        actor=actor,
        target=target_player,
        cards=cards,
        event_type=EventType.SUBMITTED_FOR,
        now=now,
        event_id=event_id,
    )


def add_special_hand(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    assert state.rules is not None
    if not state.rules.special_hands_enabled:
        raise IllegalTransition("Special hands are disabled for this room.")
    round_ = state.current_round
    if round_ is None or round_.phase not in (RoundPhase.PLAYING, RoundPhase.COLLECTING):
        raise IllegalTransition("No active round to claim a special hand on.")
    others = [p for p in state.member_ids if p != actor]
    transfers = compute_special_transfer(actor, others, state.rules, round_.round_no)
    payload = {
        "round_no": round_.round_no,
        "claimer": str(actor),
        "transfers": [t.model_dump(mode="json") for t in transfers],
    }
    return [
        _mk_event(
            state, EventType.SPECIAL_HAND, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def _target_round_index_for_void(state: RoomState) -> int:
    if not state.rounds:
        raise IllegalTransition("There's no round to void.")
    if state.rounds[-1].is_empty:
        if len(state.rounds) < 2:
            raise IllegalTransition("There's no round to void.")
        return len(state.rounds) - 2
    return len(state.rounds) - 1


def void_special_hand(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    """Take back a special hand you claimed by mistake.

    A special settles the instant it's claimed and, unlike the card-based
    part of a round, `void_last_round` deliberately leaves it alone — so
    without this an accidental tap moves money permanently. You can only
    undo your OWN claim, and only in the round you made it: past rounds are
    settled history.

    The reversal is built from the transfers actually recorded for the
    claim rather than recomputed, so it puts back exactly what was taken
    even if the rules or the table have changed since.
    """
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    round_ = state.current_round
    if round_ is None or not round_.special_counts.get(actor):
        raise IllegalTransition("You have no special hand to undo in this round.")

    mine = [t for t in round_.transfers if t.kind == TransferKind.SPECIAL and t.to_player == actor]
    # One claim bills every other player once, so the most recent claim is
    # the last group of that size.
    per_claim = max(1, len(mine) // round_.special_counts[actor])
    to_reverse = mine[-per_claim:]
    payload = {
        "round_no": round_.round_no,
        "claimer": str(actor),
        "transfers": [t.model_dump(mode="json") for t in to_reverse],
    }
    return [
        _mk_event(
            state,
            EventType.SPECIAL_HAND_VOIDED,
            actor,
            payload,
            _now(now),
            expected_seq + 1,
            event_id,
        )
    ]


def void_last_round(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    idx = _target_round_index_for_void(state)
    # The player who claimed the win can take it back — they're the one who
    # knows it was a misclick. The host can too, as the backstop for when
    # that player has stopped responding and the round would otherwise sit
    # in `collecting` forever.
    claimant = state.rounds[idx].winner
    if actor != state.host_id and actor != claimant:
        raise NotAuthorized("Only the host or the player who claimed the win can undo it.")
    payload = {"round_no": state.rounds[idx].round_no}
    return [
        _mk_event(
            state, EventType.ROUND_VOIDED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def end_game(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
    reason: str | None = None,
) -> list[Event]:
    """`reason` records WHY the game ended, for anything that ends a game
    without a player asking — currently only the inactivity backstop, which
    passes "stale". A player-initiated end leaves it unset; `actor` already
    says who did it. Without this the two are indistinguishable, which
    matters once ending a game creates real debts."""
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    # Ending the game finalises every balance and creates real debts, so it
    # takes the host — the same bar as starting or disbanding, and what
    # Mahjong already required.
    if actor != state.host_id:
        raise NotAuthorized("Only the host can end the game.")
    round_ = state.current_round
    if round_ is not None and round_.phase == RoundPhase.COLLECTING:
        raise IllegalTransition(
            "A round is still being collected — void it before ending the game."
        )
    payload: dict[str, Any] = {"reason": reason} if reason else {}
    return [
        _mk_event(
            state, EventType.GAME_ENDED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


# ============================================================
# apply: the single source of truth for how an event mutates state.
# ============================================================


def apply(state: RoomState, event: Event) -> RoomState:
    """Fold one event into state. Pure: returns a new RoomState, never mutates the input."""
    if event.seq != state.seq + 1:
        raise SeqConflict(expected=state.seq + 1, actual=event.seq)

    new = state.model_copy(deep=True)
    new.seq = event.seq

    if event.type == EventType.PLAYER_JOINED:
        pid = UUID(event.payload["player_id"])
        new.members[pid] = Member(
            player_id=pid,
            display_name=event.payload["display_name"],
            is_guest=event.payload.get("is_guest", False),
            seat=len(new.members),
        )
        new.balances[pid] = 0

    elif event.type == EventType.GAME_STARTED:
        new.rules = GameRules.model_validate(event.payload["rules"])
        new.status = RoomStatus.IN_PROGRESS
        new.rounds = [RoundState(round_no=1, phase=RoundPhase.PLAYING)]

    elif event.type == EventType.WIN_CLAIMED:
        round_ = new.rounds[-1]
        round_.phase = RoundPhase.COLLECTING
        round_.winner = UUID(event.payload["winner"])

    elif event.type in (EventType.CARDS_SUBMITTED, EventType.SUBMITTED_FOR):
        round_ = new.rounds[-1]
        round_.cards_submitted[UUID(event.payload["target_player"])] = event.payload["cards"]

    elif event.type == EventType.SPECIAL_HAND:
        round_ = new.rounds[-1]
        claimer = UUID(event.payload["claimer"])
        round_.special_counts[claimer] = round_.special_counts.get(claimer, 0) + 1
        for t in event.payload["transfers"]:
            new.balances[UUID(t["from_player"])] -= t["amount_cents"]
            new.balances[UUID(t["to_player"])] += t["amount_cents"]
            round_.transfers.append(Transfer.model_validate(t))

    elif event.type == EventType.SPECIAL_HAND_VOIDED:
        round_ = new.rounds[-1]
        claimer = UUID(event.payload["claimer"])
        round_.special_counts[claimer] = max(0, round_.special_counts.get(claimer, 0) - 1)
        for t in event.payload["transfers"]:
            new.balances[UUID(t["from_player"])] += t["amount_cents"]
            new.balances[UUID(t["to_player"])] -= t["amount_cents"]
        reversed_count = len(event.payload["transfers"])
        kept = []
        removed = 0
        # Drop the reversed claim's transfers from the tail, leaving any
        # earlier claims in place.
        for t in reversed(round_.transfers):
            if (
                removed < reversed_count
                and t.kind == TransferKind.SPECIAL
                and t.to_player == claimer
            ):
                removed += 1
                continue
            kept.append(t)
        round_.transfers = list(reversed(kept))

    elif event.type == EventType.ROUND_RESOLVED:
        round_ = new.rounds[-1]
        round_.phase = RoundPhase.RESOLVED
        round_.winner = UUID(event.payload["winner"])
        round_.rules_snapshot = new.rules
        round_.engine_version = event.payload["engine_version"]
        for t in event.payload["transfers"]:
            new.balances[UUID(t["from_player"])] -= t["amount_cents"]
            new.balances[UUID(t["to_player"])] += t["amount_cents"]
            round_.transfers.append(Transfer.model_validate(t))
        new.rounds.append(RoundState(round_no=round_.round_no + 1, phase=RoundPhase.PLAYING))

    elif event.type == EventType.ROUND_VOIDED:
        # Only the card-based resolution (cards/difference/base) is reversed.
        # Special hands settle immediately and independently of round
        # resolution, so they survive a void — undoing a specific special
        # claim isn't supported yet (see machine.py module docstring).
        round_no = event.payload["round_no"]
        idx = next(i for i, r in enumerate(new.rounds) if r.round_no == round_no)
        round_ = new.rounds[idx]
        kept_transfers = []
        for t in round_.transfers:
            if t.kind == TransferKind.SPECIAL:
                kept_transfers.append(t)
                continue
            new.balances[t.from_player] += t.amount_cents
            new.balances[t.to_player] -= t.amount_cents
        reverted = RoundState(
            round_no=round_.round_no,
            phase=RoundPhase.PLAYING,
            special_counts=dict(round_.special_counts),
            transfers=kept_transfers,
        )
        new.rounds = new.rounds[:idx] + [reverted]

    elif event.type == EventType.GAME_ENDED:
        new.status = RoomStatus.ENDED
        new.ended_at = event.created_at
        if new.rounds and new.rounds[-1].is_empty:
            new.rounds.pop()

    elif event.type == EventType.PLAYER_STEPPED_OUT:
        pid = UUID(event.payload["player_id"])
        departing = new.members[pid]
        new.departed[pid] = departing.display_name
        del new.members[pid]
        # Balance deliberately survives: they played those rounds and their
        # money still has to settle with everyone else's.
        if new.host_id == pid and new.members:
            # Ending the game is host-only, so the room would be unclosable
            # if the host walked off with the title.
            new.host_id = next(iter(sorted(new.members, key=lambda p: new.members[p].seat)))

    elif event.type == EventType.PLAYER_LEFT:
        pid = UUID(event.payload["player_id"])
        del new.members[pid]
        del new.balances[pid]

    elif event.type == EventType.ROOM_DISBANDED:
        new.status = RoomStatus.DISBANDED
        new.ended_at = event.created_at

    else:  # pragma: no cover
        raise ValueError(f"Unknown event type: {event.type}")

    return new


def fold(state: RoomState, events: list[Event]) -> RoomState:
    """Apply a list of events in order. Used both for a live command's cascade and for replay."""
    for event in events:
        state = apply(state, event)
    return state
