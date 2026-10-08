"""Business logic behind GET /debts/me and the mark-paid/approve/reject
actions. Settlement rows themselves are created at game-end time (see
events_store.append_events) — this module only reads and transitions them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import events as events_table
from .db import guests as guests_table
from .db import settlements as settlements_table
from .events_store import rebuild_many
from .identity import identity_ids
from .time import utcnow
from .users_service import profiles_for


class DebtView(BaseModel):
    settlement_id: UUID
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    counterparty_id: UUID
    counterparty_display_name: str
    amount_cents: int
    status: Literal["pending", "marked_paid", "approved"]
    created_at: datetime
    updated_at: datetime
    # Where this debt came from: the player who ended the game, or the
    # inactivity backstop (auto_ended). A debt nobody remembers agreeing to
    # is exactly the thing that erodes trust in the numbers.
    ended_by: str | None
    auto_ended: bool
    # A guest nobody has claimed yet can't mark anything paid or confirm
    # it, so the account holder settles it alone (see settle()).
    counterparty_is_guest: bool = False


class DebtsResponse(BaseModel):
    owing: list[DebtView]  # player_id == from_player — money I owe
    owed: list[DebtView]  # player_id == to_player — money owed to me


class DebtActionResult(BaseModel):
    settlement_id: UUID
    status: Literal["pending", "marked_paid", "approved"]
    updated_at: datetime


class SettlementNotFound(Exception):
    pass


class SettlementForbidden(Exception):
    pass


class SettlementInvalidTransition(Exception):
    pass


async def _guests_by_id(session: AsyncSession, ids: set[UUID]) -> dict[UUID, Any]:
    if not ids:
        return {}
    rows = (
        await session.execute(select(guests_table).where(guests_table.c.guest_id.in_(ids)))
    ).all()
    return {row.guest_id: row for row in rows}


async def build_debts_for(session: AsyncSession, player_id: UUID) -> DebtsResponse:
    ids = await identity_ids(session, player_id)
    rows = (
        await session.execute(
            select(settlements_table).where(
                or_(
                    settlements_table.c.from_player.in_(ids),
                    settlements_table.c.to_player.in_(ids),
                )
            )
        )
    ).all()
    counterparties = {row.to_player if row.from_player in ids else row.from_player for row in rows}
    guests = await _guests_by_id(session, counterparties)
    claimed_by = {gid: g.claimed_by for gid, g in guests.items() if g.claimed_by}
    claimed_profiles = await profiles_for(session, list(set(claimed_by.values())))

    room_ids = {row.room_id for row in rows}
    names_by_room: dict[UUID, dict[UUID, str]] = {}
    # Every room in two queries, not two per room — debts are never
    # archived, so this list only grows.
    states = await rebuild_many(session, list(room_ids))
    for room_id, state in states.items():
        names_by_room[room_id] = {pid: m.display_name for pid, m in state.members.items()}
        # Someone who stepped out mid-game is no longer a member but is
        # still owed (or owes) money, so their name has to come from
        # somewhere — the directory added with friends.
        for pid in state.balances:
            names_by_room[room_id].setdefault(pid, "")

    # How each of these games ended — see DebtView's comment.
    end_rows = (
        await session.execute(
            select(events_table.c.room_id, events_table.c.actor, events_table.c.payload).where(
                events_table.c.room_id.in_(room_ids),
                events_table.c.type == "game_ended",
            )
        )
    ).all()
    end_by_room = {row.room_id: row for row in end_rows}

    # Fill any gaps from the user directory in one query.
    missing = [pid for names in names_by_room.values() for pid, name in names.items() if not name]
    if missing:
        directory = await profiles_for(session, missing)
        for names in names_by_room.values():
            for pid, name in list(names.items()):
                if not name:
                    profile = directory.get(pid)
                    names[pid] = profile.display_name if profile else "Former player"

    owing: list[DebtView] = []
    owed: list[DebtView] = []
    for row in rows:
        is_owing = row.from_player in ids
        counterparty_id = row.to_player if is_owing else row.from_player
        is_unclaimed_guest = counterparty_id in guests and counterparty_id not in claimed_by
        counterparty_name = names_by_room[row.room_id].get(counterparty_id, "Player")
        # A guest who has since claimed their games is that account now.
        if counterparty_id in claimed_by:
            counterparty_id = claimed_by[counterparty_id]
            profile = claimed_profiles.get(counterparty_id)
            if profile:
                counterparty_name = profile.display_name
        end_row = end_by_room.get(row.room_id)
        auto_ended = bool(end_row is not None and (end_row.payload or {}).get("reason") == "stale")
        ended_by: str | None = None
        if end_row is not None and not auto_ended and end_row.actor is not None:
            ended_by = names_by_room[row.room_id].get(end_row.actor)
        view = DebtView(
            settlement_id=row.id,
            room_id=row.room_id,
            game_type=row.game_type,
            counterparty_id=counterparty_id,
            counterparty_display_name=counterparty_name,
            counterparty_is_guest=is_unclaimed_guest,
            amount_cents=row.amount_cents,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            ended_by=ended_by,
            auto_ended=auto_ended,
        )
        (owing if is_owing else owed).append(view)

    owing.sort(key=lambda v: v.created_at, reverse=True)
    owed.sort(key=lambda v: v.created_at, reverse=True)
    return DebtsResponse(owing=owing, owed=owed)


DebtStatus = Literal["pending", "marked_paid", "approved"]


async def _transition(
    session: AsyncSession,
    settlement_id: UUID,
    actor_id: UUID,
    *,
    authorized_column: str,
    expected_status: DebtStatus,
    new_status: DebtStatus,
) -> DebtActionResult:
    row = (
        await session.execute(
            select(settlements_table).where(settlements_table.c.id == settlement_id)
        )
    ).first()
    if row is None:
        raise SettlementNotFound(settlement_id)
    if getattr(row, authorized_column) not in await identity_ids(session, actor_id):
        raise SettlementForbidden(settlement_id)
    if row.status != expected_status:
        raise SettlementInvalidTransition(
            f"Expected status '{expected_status}', found '{row.status}'."
        )

    now = utcnow()
    result = await session.execute(
        update(settlements_table)
        .where(
            settlements_table.c.id == settlement_id, settlements_table.c.status == expected_status
        )
        .values(status=new_status, updated_at=now)
    )
    assert isinstance(result, CursorResult)
    if result.rowcount == 0:
        raise SettlementInvalidTransition("This debt was already updated — please refresh.")
    await session.commit()
    return DebtActionResult(settlement_id=settlement_id, status=new_status, updated_at=now)


async def mark_paid(session: AsyncSession, settlement_id: UUID, actor_id: UUID) -> DebtActionResult:
    return await _transition(
        session,
        settlement_id,
        actor_id,
        authorized_column="from_player",
        expected_status="pending",
        new_status="marked_paid",
    )


async def approve(session: AsyncSession, settlement_id: UUID, actor_id: UUID) -> DebtActionResult:
    return await _transition(
        session,
        settlement_id,
        actor_id,
        authorized_column="to_player",
        expected_status="marked_paid",
        new_status="approved",
    )


async def reject(session: AsyncSession, settlement_id: UUID, actor_id: UUID) -> DebtActionResult:
    return await _transition(
        session,
        settlement_id,
        actor_id,
        authorized_column="to_player",
        expected_status="marked_paid",
        new_status="pending",
    )


async def settle(session: AsyncSession, settlement_id: UUID, actor_id: UUID) -> DebtActionResult:
    """Close a debt with a guest nobody has claimed, from either side, in one
    step. The usual two-step (debtor marks paid, creditor confirms) needs
    both people to have the app; a guest doesn't."""
    row = (
        await session.execute(
            select(settlements_table).where(settlements_table.c.id == settlement_id)
        )
    ).first()
    if row is None:
        raise SettlementNotFound(settlement_id)
    ids = await identity_ids(session, actor_id)
    if row.from_player in ids:
        other = row.to_player
    elif row.to_player in ids:
        other = row.from_player
    else:
        raise SettlementForbidden(settlement_id)
    guest = (await _guests_by_id(session, {other})).get(other)
    if guest is None or guest.claimed_by is not None:
        raise SettlementInvalidTransition("Only a debt with a guest can be settled this way.")
    if row.status == "approved":
        raise SettlementInvalidTransition("This debt is already settled.")

    now = utcnow()
    result = await session.execute(
        update(settlements_table)
        .where(settlements_table.c.id == settlement_id, settlements_table.c.status == row.status)
        .values(status="approved", updated_at=now)
    )
    assert isinstance(result, CursorResult)
    if result.rowcount == 0:
        raise SettlementInvalidTransition("This debt was already updated — please refresh.")
    await session.commit()
    return DebtActionResult(settlement_id=settlement_id, status="approved", updated_at=now)
