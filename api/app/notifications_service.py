"""Everything waiting on this player, in one request.

Deliberately one endpoint rather than the home page asking /debts/me and
/friends separately: the database is a long way from the API (~110ms a
statement) and the home screen already fetches the active room and the
profile. A bell that cost two more round trips would undo the work that made
opening the app quick.

"Pending" means pending on YOU. A debt you've already marked paid is waiting
on the other person, and a debt owed to you that nobody has paid yet is
waiting on them — neither belongs here.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import friendships as friendships_table
from .db import settlements as settlements_table
from .users_service import profiles_for

NotificationKind = Literal["debt_to_pay", "debt_to_approve", "friend_request"]


class Notification(BaseModel):
    kind: NotificationKind
    #: Who it involves — the person you owe, who says they paid you, or who
    #: asked to be friends. Display name, as a fallback for the handle.
    counterparty: str
    #: Their handle, which is what the bell actually shows. None only for
    #: someone missing from the directory entirely — see the note on
    #: `names` below.
    counterparty_username: str | None = None
    #: Only set for the debt kinds. Formatting stays on the client.
    amount_cents: int | None = None
    #: The settlement or friendship this came from, so the UI can deep-link.
    ref_id: UUID


class NotificationsResponse(BaseModel):
    items: list[Notification]
    total: int


async def build_notifications_for(session: AsyncSession, player_id: UUID) -> NotificationsResponse:
    settlements = (
        await session.execute(
            select(settlements_table).where(
                or_(
                    # Yours to pay.
                    (settlements_table.c.from_player == player_id)
                    & (settlements_table.c.status == "pending"),
                    # Yours to confirm you received.
                    (settlements_table.c.to_player == player_id)
                    & (settlements_table.c.status == "marked_paid"),
                )
            )
        )
    ).all()

    requests = (
        await session.execute(
            select(friendships_table).where(
                friendships_table.c.addressee_id == player_id,
                friendships_table.c.status == "pending",
            )
        )
    ).all()

    # Names come from the directory in a single query. Replaying each room
    # would also work and would even cover players who stepped out, but
    # everyone is in the directory now (users_service.ensure_user), and a
    # full event replay per room is far too much work for a bell.
    involved = {
        pid for row in settlements for pid in (row.from_player, row.to_player) if pid != player_id
    } | {row.requester_id for row in requests}
    # Anyone who creates or joins a room is recorded (users_service.
    # ensure_user), so a miss here means a game played before the directory
    # existed — scripts/backfill_users.py is what fills those in.
    directory = await profiles_for(session, list(involved))

    items: list[Notification] = []
    for row in settlements:
        if row.from_player == player_id:
            other = directory.get(row.to_player)
            items.append(
                Notification(
                    kind="debt_to_pay",
                    counterparty=other.display_name if other else "Someone",
                    counterparty_username=other.username if other else None,
                    amount_cents=row.amount_cents,
                    ref_id=row.id,
                )
            )
        else:
            other = directory.get(row.from_player)
            items.append(
                Notification(
                    kind="debt_to_approve",
                    counterparty=other.display_name if other else "Someone",
                    counterparty_username=other.username if other else None,
                    amount_cents=row.amount_cents,
                    ref_id=row.id,
                )
            )
    for row in requests:
        other = directory.get(row.requester_id)
        items.append(
            Notification(
                kind="friend_request",
                counterparty=other.display_name if other else "Someone",
                counterparty_username=other.username if other else None,
                ref_id=row.id,
            )
        )

    return NotificationsResponse(items=items, total=len(items))
