"""The Mahjong room/hand state machine.

Mirrors taidi_core/machine.py's split (command functions validate and
return events; apply() is the sole source of truth for state mutation) but
for Mahjong's shape: no round-based collecting phase — YAO/GANG never close
a hand, only HU/NO_WIN do, and closing a hand also runs dealer/wind
advancement.

Design notes:
- Seats are fixed 0-3 slots, defaulting to join order; the host can
  rearrange them with assign_seats before starting.
- Dealer/wind rule (confirmed with the product owner — close to standard
  mahjong but not identical): outside the last seat of the last wind, a WIN
  rotates the dealer to the next seat unless the dealer themselves won (in
  which case they stay) — GANG presence doesn't affect a win. A NO WIN
  repeats the same dealer unless a GANG happened this hand, in which case
  it rotates anyway. Either way, wrapping seat 3->0 advances the wind. The
  last seat of the last wind is different: it only closes the wind cycle
  on a WIN, regardless of who won — a no-win hand there just repeats,
  regardless of GANGs. Cycle completion sets pending_wind_decision; only
  the host's continue_wind or end_game can proceed from there.
- Closing a hand (HU or NO_WIN) computes the dealer/wind outcome up front
  (`_plan_hand_close`) and folds it into the event payload, so apply() never
  recomputes it — replay stays exact even if the rule itself changes later
  (old events keep the outcome they were closed with).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from taidi_core.errors import IllegalTransition, NotAuthorized, SeqConflict
from taidi_core.models import REPLAY, Member, RoomStatus

from .models import (
    Declaration,
    Event,
    EventType,
    HandState,
    MahjongRules,
    RoomState,
    Transfer,
    TransferKind,
)
from .rules import (
    ENGINE_VERSION,
    gang_amount_angang,
    gang_amount_other,
    gang_amount_self,
    hu_amount_bao,
    hu_amount_direct,
    hu_amount_zimo_each,
    klppdd_amount_each,
    klppdd_amount_single_payer,
    yao_amount,
    zimo_bonus_amount,
)

SEAT_COUNT = 4
MAX_WINDS = 4


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


def _require_member(state: RoomState, player_id: UUID) -> None:
    if player_id not in state.members:
        raise NotAuthorized("Not a member of this room.")


def _require_in_progress(state: RoomState) -> None:
    if state.status != RoomStatus.IN_PROGRESS:
        raise IllegalTransition("The game hasn't started yet.")


def _require_open_hand(state: RoomState) -> HandState:
    hand = state.current_hand
    if hand is None or hand.closed:
        raise IllegalTransition("Waiting for the host to continue or end.")
    return hand


def _seat_player(state: RoomState, seat: int) -> UUID:
    # Looked up by the seat number itself, not by position in a seat-sorted
    # list — the two only agree while seats are exactly 0-3.
    if isinstance(seat, bool) or not isinstance(seat, int):
        raise IllegalTransition("A seat is a number from 0 to 3.")
    for pid, member in state.members.items():
        if member.seat == seat:
            return pid
    raise IllegalTransition(f"No player in seat {seat}.")


def _lowest_free_seat(members: dict[UUID, Member]) -> int:
    """Seats can't just be len(members): after someone leaves the lobby that
    number can already be taken, and two players in one seat means
    declaring against a seat charges the wrong person."""
    taken = {m.seat for m in members.values()}
    return next(s for s in range(len(members) + 1) if s not in taken)


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
    if len(state.members) >= SEAT_COUNT:
        raise IllegalTransition("Mahjong rooms only take 4 players.")
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


MAX_GUEST_NAME = 40


def add_guest(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    guest_id: UUID,
    display_name: str,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    """The host seats someone with no account. One phone can then run the
    whole table: the host acts for guests (the API's `as_player`), and a
    guest can claim the game for a real account afterwards."""
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can add guests.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Guests can only be added before the game starts.")
    name = " ".join(display_name.split())
    if not name or len(name) > MAX_GUEST_NAME:
        raise IllegalTransition(f"A guest needs a name of 1-{MAX_GUEST_NAME} characters.")
    if any(m.display_name.casefold() == name.casefold() for m in state.members.values()):
        raise IllegalTransition(f"Someone called {name} is already at the table.")
    if guest_id in state.members:
        raise IllegalTransition("That guest is already at the table.")
    if len(state.members) >= SEAT_COUNT:
        raise IllegalTransition("Mahjong rooms only take 4 players.")
    payload = {"player_id": str(guest_id), "display_name": name, "is_guest": True}
    return [
        _mk_event(
            state, EventType.PLAYER_JOINED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def remove_guest(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    guest_id: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can remove guests.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Guests can only be removed before the game starts.")
    member = state.members.get(guest_id)
    if member is None or not member.is_guest:
        raise IllegalTransition("No such guest at this table.")
    payload = {"player_id": str(guest_id)}
    return [
        _mk_event(
            state, EventType.PLAYER_LEFT, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def assign_seats(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    seat_map: dict[UUID, int],
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can rearrange seats.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Can't rearrange seats once the game has started.")
    if len(state.members) != SEAT_COUNT:
        raise IllegalTransition("Need exactly 4 players before assigning seats.")
    if not set(seat_map) <= set(state.members):
        raise IllegalTransition("Can only seat players who are in the room.")
    # A partial map (e.g. just the two players being swapped) is merged over
    # the current seats; the event always records the full result.
    merged = {pid: m.seat for pid, m in state.members.items()} | dict(seat_map)
    if sorted(merged.values()) != list(range(SEAT_COUNT)):
        raise IllegalTransition(
            "Seat assignment must place each of the 4 players in a distinct seat 0-3."
        )
    payload = {str(pid): seat for pid, seat in merged.items()}
    return [
        _mk_event(
            state, EventType.SEATS_ASSIGNED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def start_game(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    rules: MahjongRules,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can start the game.")
    if state.status != RoomStatus.LOBBY:
        raise IllegalTransition("Game already started.")
    if len(state.members) != SEAT_COUNT:
        raise IllegalTransition("Mahjong needs exactly 4 players to start.")
    if sorted(m.seat for m in state.members.values()) != list(range(SEAT_COUNT)):
        raise IllegalTransition("Every seat 0-3 needs exactly one player before starting.")
    payload = {"rules": rules.model_dump(mode="json")}
    return [
        _mk_event(
            state, EventType.GAME_STARTED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def declare_yao(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    target_seat: int,
    an: bool,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    hand = _require_open_hand(state)
    assert state.rules is not None
    target_player = _seat_player(state, target_seat)
    amount = yao_amount(state.rules, an)
    if target_player == actor:
        others = [p for p in state.member_ids_by_seat if p != actor]
        transfers = [
            Transfer(
                from_player=p,
                to_player=actor,
                amount_cents=amount,
                kind=TransferKind.YAO,
                hand_no=hand.hand_no,
            )
            for p in others
        ]
    else:
        transfers = [
            Transfer(
                from_player=target_player,
                to_player=actor,
                amount_cents=amount,
                kind=TransferKind.YAO,
                hand_no=hand.hand_no,
            )
        ]
    payload = {
        "hand_no": hand.hand_no,
        "target_seat": target_seat,
        "an": an,
        "transfers": [t.model_dump(mode="json") for t in transfers],
    }
    return [
        _mk_event(
            state, EventType.YAO_DECLARED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def declare_gang(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    target: int | Literal["angang"],
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    hand = _require_open_hand(state)
    assert state.rules is not None
    others = [p for p in state.member_ids_by_seat if p != actor]

    if target != "angang" and (isinstance(target, bool) or not isinstance(target, int)):
        raise IllegalTransition("A gang targets a seat or 'angang'.")
    if target == "angang":
        amount = gang_amount_angang(state.rules)
        transfers = [
            Transfer(
                from_player=p,
                to_player=actor,
                amount_cents=amount,
                kind=TransferKind.GANG,
                hand_no=hand.hand_no,
            )
            for p in others
        ]
    else:
        target_player = _seat_player(state, target)
        if target_player == actor:
            amount = gang_amount_self(state.rules)
            transfers = [
                Transfer(
                    from_player=p,
                    to_player=actor,
                    amount_cents=amount,
                    kind=TransferKind.GANG,
                    hand_no=hand.hand_no,
                )
                for p in others
            ]
        else:
            amount = gang_amount_other(state.rules)
            transfers = [
                Transfer(
                    from_player=target_player,
                    to_player=actor,
                    amount_cents=amount,
                    kind=TransferKind.GANG,
                    hand_no=hand.hand_no,
                )
            ]

    payload = {
        "hand_no": hand.hand_no,
        "target": target,
        "transfers": [t.model_dump(mode="json") for t in transfers],
    }
    return [
        _mk_event(
            state, EventType.GANG_DECLARED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def _plan_hand_close(hand: HandState, *, is_win: bool, should_rotate: bool) -> dict[str, Any]:
    """Computes the dealer/wind outcome of closing `hand`. Pure — doesn't
    touch RoomState. Folded into the closing event's payload so apply()
    never recomputes it and replay stays exact.

    `should_rotate` is the caller's job to compute: on a win it's "the
    dealer didn't win"; on a no-win it's "a gang happened this hand". The
    last seat of the last wind ignores it — only a WIN closes that cycle,
    and a no-win there just repeats regardless of gangs. Past wind 4 (the
    host chose to continue) every wind's last seat is such a boundary, so
    the host is asked again each time."""
    is_final_hand = hand.wind >= MAX_WINDS and hand.dealer_seat == SEAT_COUNT - 1

    if is_final_hand:
        return {
            "pending_wind_decision": is_win,
            "next_wind": hand.wind,
            "next_dealer_seat": hand.dealer_seat,
        }

    if should_rotate:
        next_seat = (hand.dealer_seat + 1) % SEAT_COUNT
        next_wind = hand.wind + 1 if next_seat == 0 else hand.wind
    else:
        next_seat = hand.dealer_seat
        next_wind = hand.wind
    return {"pending_wind_decision": False, "next_wind": next_wind, "next_dealer_seat": next_seat}


def declare_hu(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    mode: Literal["direct", "zimo", "bao"],
    target_seat: int | None,
    tai: int,
    zimo_bonus: bool = False,
    klppdd: bool = False,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    _require_in_progress(state)
    _require_member(state, actor)
    hand = _require_open_hand(state)
    assert state.rules is not None
    if not 1 <= tai <= state.rules.max_tai:
        raise IllegalTransition(f"Tai must be between 1 and {state.rules.max_tai}.")
    if zimo_bonus and mode != "zimo":
        raise IllegalTransition("Zimo bonus only applies to a self-drawn win.")

    if mode == "zimo":
        amount = hu_amount_zimo_each(state.rules, tai)
        others = [p for p in state.member_ids_by_seat if p != actor]
        transfers = [
            Transfer(
                from_player=p,
                to_player=actor,
                amount_cents=amount,
                kind=TransferKind.HU,
                hand_no=hand.hand_no,
            )
            for p in others
        ]
        if zimo_bonus:
            bonus = zimo_bonus_amount(state.rules)
            transfers += [
                Transfer(
                    from_player=p,
                    to_player=actor,
                    amount_cents=bonus,
                    kind=TransferKind.ZIMO_BONUS,
                    hand_no=hand.hand_no,
                )
                for p in others
            ]
        if klppdd:
            bonus = klppdd_amount_each(state.rules)
            transfers += [
                Transfer(
                    from_player=p,
                    to_player=actor,
                    amount_cents=bonus,
                    kind=TransferKind.KLPPDD,
                    hand_no=hand.hand_no,
                )
                for p in others
            ]
    else:
        if target_seat is None:
            raise IllegalTransition(f"{mode} needs a target seat.")
        target_player = _seat_player(state, target_seat)
        if target_player == actor:
            raise IllegalTransition("Can't target yourself for a direct or bao win.")
        if mode == "direct":
            amount = hu_amount_direct(state.rules, tai)
            kind = TransferKind.HU
        else:  # bao
            amount = hu_amount_bao(state.rules, tai)
            kind = TransferKind.BAO
        transfers = [
            Transfer(
                from_player=target_player,
                to_player=actor,
                amount_cents=amount,
                kind=kind,
                hand_no=hand.hand_no,
            )
        ]
        if klppdd:
            transfers.append(
                Transfer(
                    from_player=target_player,
                    to_player=actor,
                    amount_cents=klppdd_amount_single_payer(state.rules),
                    kind=TransferKind.KLPPDD,
                    hand_no=hand.hand_no,
                )
            )

    close = _plan_hand_close(
        hand, is_win=True, should_rotate=state.members[actor].seat != hand.dealer_seat
    )
    payload = {
        "hand_no": hand.hand_no,
        "mode": mode,
        "target_seat": target_seat,
        "tai": tai,
        "zimo_bonus": zimo_bonus,
        "klppdd": klppdd,
        "winner": str(actor),
        "transfers": [t.model_dump(mode="json") for t in transfers],
        "engine_version": ENGINE_VERSION,
        **close,
    }
    return [
        _mk_event(
            state, EventType.HU_DECLARED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def declare_no_win(
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
    hand = _require_open_hand(state)
    close = _plan_hand_close(hand, is_win=False, should_rotate=hand.had_gang)
    payload = {"hand_no": hand.hand_no, **close}
    return [
        _mk_event(
            state, EventType.NO_WIN_DECLARED, actor, payload, _now(now), expected_seq + 1, event_id
        )
    ]


def continue_wind(
    state: RoomState,
    *,
    expected_seq: int,
    actor: UUID,
    now: datetime | None = None,
    event_id: UUID | None = None,
) -> list[Event]:
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can continue past the last wind.")
    _require_in_progress(state)
    if not state.pending_wind_decision:
        raise IllegalTransition("No wind decision is pending.")
    return [
        _mk_event(state, EventType.WIND_CONTINUED, actor, {}, _now(now), expected_seq + 1, event_id)
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
    """See taidi_core.machine.end_game for what `reason` is for."""
    _check_seq(state, expected_seq)
    if actor != state.host_id:
        raise NotAuthorized("Only the host can end the game.")
    _require_in_progress(state)
    payload: dict[str, Any] = {"reason": reason} if reason else {}
    return [
        _mk_event(
            state, EventType.GAME_ENDED, actor, payload, _now(now), expected_seq + 1, event_id
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


# ============================================================
# apply: the single source of truth for how an event mutates state.
# ============================================================


def _apply_transfers(
    state: RoomState, hand: HandState, payload_transfers: list[dict[str, Any]]
) -> None:
    # Payloads hold amounts in the rules' units — chips for games from
    # before dollars — so this is the one place they become cents.
    assert state.rules is not None
    per_unit = state.rules.cents_per_unit
    for t in payload_transfers:
        cents = t["amount_cents"] * per_unit
        state.balances[UUID(t["from_player"])] -= cents
        state.balances[UUID(t["to_player"])] += cents
        hand.transfers.append(Transfer.model_validate({**t, "amount_cents": cents}))


def _open_next_hand(state: RoomState, closed: HandState, payload: dict[str, Any]) -> None:
    state.pending_wind_decision = payload["pending_wind_decision"]
    if not state.pending_wind_decision:
        state.hands.append(
            HandState(
                hand_no=closed.hand_no + 1,
                wind=payload["next_wind"],
                dealer_seat=payload["next_dealer_seat"],
            )
        )


def apply(state: RoomState, event: Event) -> RoomState:
    """Fold one event into state. Pure: returns a new RoomState, never mutates the input."""
    new = state.model_copy(deep=True)
    _apply_in_place(new, event)
    return new


def _apply_in_place(new: RoomState, event: Event) -> None:
    """apply()'s body, mutating `new` directly. Split out so fold() can copy
    once per replay rather than once per event — a per-event deep copy of a
    state whose round history grows with every event made replay quadratic
    (a 100-round game took seconds to rebuild on every poll)."""
    if event.room_id != new.room_id:
        raise ValueError(f"Event {event.event_id} belongs to another room.")
    if event.seq != new.seq + 1:
        raise SeqConflict(expected=new.seq + 1, actual=event.seq)

    new.seq = event.seq

    if event.type == EventType.PLAYER_JOINED:
        pid = UUID(event.payload["player_id"])
        new.members[pid] = Member(
            player_id=pid,
            display_name=event.payload["display_name"],
            is_guest=event.payload.get("is_guest", False),
            seat=_lowest_free_seat(new.members),
        )
        new.balances[pid] = 0

    elif event.type == EventType.SEATS_ASSIGNED:
        for pid_str, seat in event.payload.items():
            new.members[UUID(pid_str)].seat = seat

    elif event.type == EventType.GAME_STARTED:
        new.rules = MahjongRules.from_stored(event.payload["rules"], context=REPLAY)
        new.status = RoomStatus.IN_PROGRESS
        new.hands = [HandState(hand_no=1, wind=1, dealer_seat=0)]

    elif event.type == EventType.YAO_DECLARED:
        # `an` comes from the event, not the transfers: a self-drawn yao and
        # an anyao produce the same shape. See models.Declaration.
        assert event.actor is not None  # declare_yao always records the declarer
        new.hands[-1].declarations.append(
            Declaration(
                player_id=event.actor,
                kind="yao",
                concealed=bool(event.payload.get("an", False)),
            )
        )
        _apply_transfers(new, new.hands[-1], event.payload["transfers"])

    elif event.type == EventType.GANG_DECLARED:
        new.hands[-1].had_gang = True
        assert event.actor is not None  # declare_gang always records the declarer
        new.hands[-1].declarations.append(
            Declaration(
                player_id=event.actor,
                kind="gang",
                concealed=event.payload.get("target") == "angang",
            )
        )
        _apply_transfers(new, new.hands[-1], event.payload["transfers"])

    elif event.type == EventType.HU_DECLARED:
        hand = new.hands[-1]
        hand.closed = True
        hand.winner = UUID(event.payload["winner"])
        hand.mode = event.payload.get("mode")
        hand.tai = event.payload.get("tai")
        hand.zimo_bonus = event.payload.get("zimo_bonus", False)
        hand.klppdd = event.payload.get("klppdd", False)
        _apply_transfers(new, hand, event.payload["transfers"])
        _open_next_hand(new, hand, event.payload)

    elif event.type == EventType.NO_WIN_DECLARED:
        hand = new.hands[-1]
        hand.closed = True
        _open_next_hand(new, hand, event.payload)

    elif event.type == EventType.WIND_CONTINUED:
        new.pending_wind_decision = False
        last = new.hands[-1]
        new.hands.append(HandState(hand_no=last.hand_no + 1, wind=last.wind + 1, dealer_seat=0))

    elif event.type == EventType.GAME_ENDED:
        new.status = RoomStatus.ENDED
        new.ended_at = event.created_at
        new.pending_wind_decision = False

    elif event.type == EventType.PLAYER_LEFT:
        pid = UUID(event.payload["player_id"])
        del new.members[pid]
        del new.balances[pid]

    elif event.type == EventType.ROOM_DISBANDED:
        new.status = RoomStatus.DISBANDED
        new.ended_at = event.created_at

    else:  # pragma: no cover
        raise ValueError(f"Unknown event type: {event.type}")


def fold(state: RoomState, events: list[Event]) -> RoomState:
    """Apply a list of events in order. Used both for a live command's cascade and for replay.
    Pure like apply(): the input is copied once up front, never mutated."""
    new = state.model_copy(deep=True)
    for event in events:
        _apply_in_place(new, event)
    return new
