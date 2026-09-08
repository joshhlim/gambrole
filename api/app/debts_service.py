"""Business logic behind GET /debts/me and the mark-paid/approve/reject
actions. Settlement rows themselves are created at game-end time (see
events_store.append_events) — this module only reads and transitions them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db import settlements as settlements_table
from .events_store import rebuild_mahjong_state_with_invite, rebuild_taidi_state_with_invite
from .time import utcnow


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


async def build_debts_for(session: AsyncSession, player_id: UUID) -> DebtsResponse:
    rows = (
        await session.execute(
            select(settlements_table).where(
                or_(
                    settlements_table.c.from_player == player_id,
                    settlements_table.c.to_player == player_id,
                )
            )
        )
    ).all()

    room_ids = {row.room_id for row in rows}
    names_by_room: dict[UUID, dict[UUID, str]] = {}
    game_type_by_room = {row.room_id: row.game_type for row in rows}
    for room_id in room_ids:
        if game_type_by_room[room_id] == "mahjong":
            state, _invite_code = await rebuild_mahjong_state_with_invite(session, room_id)
        else:
            state, _invite_code = await rebuild_taidi_state_with_invite(session, room_id)
        names_by_room[room_id] = {pid: m.display_name for pid, m in state.members.items()}

    owing: list[DebtView] = []
    owed: list[DebtView] = []
    for row in rows:
        is_owing = row.from_player == player_id
        counterparty_id = row.to_player if is_owing else row.from_player
        view = DebtView(
            settlement_id=row.id,
            room_id=row.room_id,
            game_type=row.game_type,
            counterparty_id=counterparty_id,
            counterparty_display_name=names_by_room[row.room_id].get(counterparty_id, "Player"),
            amount_cents=row.amount_cents,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        (owing if is_owing else owed).append(view)

    owing.sort(key=lambda v: v.created_at, reverse=True)
    owed.sort(key=lambda v: v.created_at, reverse=True)
    return DebtsResponse(owing=owing, owed=owed)


async def _transition(
    session: AsyncSession,
    settlement_id: UUID,
    actor_id: UUID,
    *,
    authorized_column: str,
    expected_status: str,
    new_status: str,
) -> DebtActionResult:
    row = (
        await session.execute(
            select(settlements_table).where(settlements_table.c.id == settlement_id)
        )
    ).first()
    if row is None:
        raise SettlementNotFound(settlement_id)
    if getattr(row, authorized_column) != actor_id:
        raise SettlementForbidden(settlement_id)
    if row.status != expected_status:
        raise SettlementInvalidTransition(
            f"Expected status '{expected_status}', found '{row.status}'."
        )

    now = utcnow()
    result = await session.execute(
        update(settlements_table)
        .where(settlements_table.c.id == settlement_id, settlements_table.c.status == expected_status)
        .values(status=new_status, updated_at=now)
    )
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
