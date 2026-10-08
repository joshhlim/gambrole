"""Groups: a regular crew with its own running leaderboard.

A group is just a named set of accounts with an invite code. Games created
"in" a group (rooms.group_id) are what its leaderboard and recent games are
built from — everyone who played in them counts, guests included (by the
name they played under), with any guest who has since claimed their games
folded into that account.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .db import group_members as members_table
from .db import groups as groups_table
from .db import guests as guests_table
from .db import rooms as rooms_table
from .events_store import generate_invite_code, rebuild_many
from .time import utcnow
from .users_service import UserProfile, profiles_for

MAX_GROUP_NAME = 60
MAX_GROUP_MEMBERS = 50
RECENT_GAMES = 20


class GroupNotFound(Exception):
    pass


class GroupForbidden(Exception):
    pass


class GroupError(Exception):
    pass


class GroupSummary(BaseModel):
    group_id: UUID
    name: str
    member_count: int
    games_played: int
    last_played: datetime | None
    is_owner: bool


class LeaderboardRow(BaseModel):
    player_id: UUID
    display_name: str
    profile: UserProfile | None  # None for a guest who hasn't claimed
    sessions: int
    net_cents: int
    wins: int  # sessions finished up


class GroupGame(BaseModel):
    room_id: UUID
    game_type: Literal["taidi", "mahjong"]
    ended_at: datetime
    results: list[tuple[str, int]]  # (name, net cents), best first


class GroupDetail(BaseModel):
    group_id: UUID
    name: str
    owner_id: UUID
    invite_code: str
    members: list[UserProfile]
    leaderboard: list[LeaderboardRow]
    recent_games: list[GroupGame]


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned or len(cleaned) > MAX_GROUP_NAME:
        raise GroupError(f"A group name is 1-{MAX_GROUP_NAME} characters.")
    return cleaned


async def is_member(session: AsyncSession, group_id: UUID, user_id: UUID) -> bool:
    row = (
        await session.execute(
            select(members_table.c.user_id).where(
                members_table.c.group_id == group_id, members_table.c.user_id == user_id
            )
        )
    ).first()
    return row is not None


async def _group(session: AsyncSession, group_id: UUID) -> Any:
    row = (
        await session.execute(select(groups_table).where(groups_table.c.group_id == group_id))
    ).first()
    if row is None:
        raise GroupNotFound(group_id)
    return row


async def create_group(session: AsyncSession, owner: UUID, name: str) -> UUID:
    group_id = uuid4()
    now = utcnow()
    await session.execute(
        groups_table.insert().values(
            group_id=group_id,
            name=_clean_name(name),
            owner_id=owner,
            invite_code=generate_invite_code(8),
            created_at=now,
        )
    )
    await session.execute(
        members_table.insert().values(group_id=group_id, user_id=owner, joined_at=now)
    )
    await session.commit()
    return group_id


async def my_groups(session: AsyncSession, user_id: UUID) -> list[GroupSummary]:
    mine = select(members_table.c.group_id).where(members_table.c.user_id == user_id)
    groups = (
        await session.execute(select(groups_table).where(groups_table.c.group_id.in_(mine)))
    ).all()
    if not groups:
        return []
    ids = [g.group_id for g in groups]
    count_rows = (
        await session.execute(
            select(members_table.c.group_id, func.count().label("n"))
            .where(members_table.c.group_id.in_(ids))
            .group_by(members_table.c.group_id)
        )
    ).all()
    counts: dict[UUID, int] = {row.group_id: row.n for row in count_rows}
    played = {
        row.group_id: (row.games, row.last)
        for row in (
            await session.execute(
                select(
                    rooms_table.c.group_id,
                    func.count().label("games"),
                    func.max(rooms_table.c.ended_at).label("last"),
                )
                .where(rooms_table.c.group_id.in_(ids), rooms_table.c.status == "ended")
                .group_by(rooms_table.c.group_id)
            )
        ).all()
    }
    summaries = [
        GroupSummary(
            group_id=g.group_id,
            name=g.name,
            member_count=counts.get(g.group_id, 0),
            games_played=played.get(g.group_id, (0, None))[0],
            last_played=played.get(g.group_id, (0, None))[1],
            is_owner=g.owner_id == user_id,
        )
        for g in groups
    ]
    # Most recently active first; never-played groups by name at the end.
    return sorted(
        summaries,
        key=lambda s: (
            s.last_played is None,
            -(s.last_played.timestamp() if s.last_played else 0),
            s.name.lower(),
        ),
    )


async def group_detail(session: AsyncSession, group_id: UUID, viewer: UUID) -> GroupDetail:
    group = await _group(session, group_id)
    if not await is_member(session, group_id, viewer):
        raise GroupForbidden(group_id)

    member_ids = [
        row.user_id
        for row in (
            await session.execute(
                select(members_table.c.user_id)
                .where(members_table.c.group_id == group_id)
                .order_by(members_table.c.joined_at)
            )
        ).all()
    ]

    rooms = (
        await session.execute(
            select(rooms_table.c.room_id, rooms_table.c.game_type).where(
                rooms_table.c.group_id == group_id, rooms_table.c.status == "ended"
            )
        )
    ).all()
    states = await rebuild_many(session, [r.room_id for r in rooms])
    game_types = {r.room_id: r.game_type for r in rooms}

    # Guests who've claimed their games count as those accounts.
    claim_rows = (
        await session.execute(
            select(guests_table.c.guest_id, guests_table.c.claimed_by).where(
                guests_table.c.room_id.in_(list(states)),
                guests_table.c.claimed_by.is_not(None),
            )
        )
    ).all()
    claimed: dict[UUID, UUID] = {row.guest_id: row.claimed_by for row in claim_rows}

    totals: dict[UUID, dict[str, Any]] = {}
    games: list[GroupGame] = []
    for room_id, state in states.items():
        names = {pid: m.display_name for pid, m in state.members.items()}
        names.update(getattr(state, "departed", {}))
        results: list[tuple[str, int]] = []
        for pid, net in state.balances.items():
            who = claimed.get(pid, pid)
            row = totals.setdefault(
                who, {"name": names.get(pid, "Player"), "sessions": 0, "net": 0, "wins": 0}
            )
            row["sessions"] += 1
            row["net"] += net
            row["wins"] += net > 0
            results.append((names.get(pid, "Player"), net))
        assert state.ended_at is not None
        games.append(
            GroupGame(
                room_id=room_id,
                game_type=game_types[room_id],
                ended_at=state.ended_at,
                results=sorted(results, key=lambda r: -r[1]),
            )
        )

    profiles = await profiles_for(session, list({*member_ids, *totals}))
    leaderboard = [
        LeaderboardRow(
            player_id=pid,
            display_name=profiles[pid].display_name if pid in profiles else t["name"],
            profile=profiles.get(pid),
            sessions=t["sessions"],
            net_cents=t["net"],
            wins=t["wins"],
        )
        for pid, t in totals.items()
    ]
    leaderboard.sort(key=lambda r: (-r.net_cents, r.display_name.lower()))
    games.sort(key=lambda g: g.ended_at, reverse=True)

    return GroupDetail(
        group_id=group.group_id,
        name=group.name,
        owner_id=group.owner_id,
        invite_code=group.invite_code,
        members=[profiles[pid] for pid in member_ids if pid in profiles],
        leaderboard=leaderboard,
        recent_games=games[:RECENT_GAMES],
    )


async def join_by_code(session: AsyncSession, user_id: UUID, code: str) -> UUID:
    group = (
        await session.execute(
            select(groups_table).where(groups_table.c.invite_code == code.strip().upper())
        )
    ).first()
    if group is None:
        raise GroupNotFound(code)
    if await is_member(session, group.group_id, user_id):
        return cast(UUID, group.group_id)  # already in — joining again is a no-op
    count = (
        await session.execute(
            select(func.count()).where(members_table.c.group_id == group.group_id)
        )
    ).scalar_one()
    if count >= MAX_GROUP_MEMBERS:
        raise GroupError(f"This group is full ({MAX_GROUP_MEMBERS} members).")
    try:
        await session.execute(
            members_table.insert().values(
                group_id=group.group_id, user_id=user_id, joined_at=utcnow()
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()  # joined twice at once — either way, they're in
    return cast(UUID, group.group_id)


async def leave(session: AsyncSession, group_id: UUID, user_id: UUID) -> None:
    group = await _group(session, group_id)
    if group.owner_id == user_id:
        # Hand the group to the longest-standing other member, or close it
        # if there's nobody left to hand it to.
        successor = (
            await session.execute(
                select(members_table.c.user_id)
                .where(members_table.c.group_id == group_id, members_table.c.user_id != user_id)
                .order_by(members_table.c.joined_at)
                .limit(1)
            )
        ).first()
        if successor is None:
            await _delete_group(session, group_id)
            return
        await session.execute(
            update(groups_table)
            .where(groups_table.c.group_id == group_id)
            .values(owner_id=successor.user_id)
        )
    await session.execute(
        delete(members_table).where(
            members_table.c.group_id == group_id, members_table.c.user_id == user_id
        )
    )
    await session.commit()


async def _delete_group(session: AsyncSession, group_id: UUID) -> None:
    # Its games stay in everyone's history; they just stop belonging to it.
    await session.execute(
        update(rooms_table).where(rooms_table.c.group_id == group_id).values(group_id=None)
    )
    await session.execute(delete(members_table).where(members_table.c.group_id == group_id))
    await session.execute(delete(groups_table).where(groups_table.c.group_id == group_id))
    await session.commit()


async def _require_owner(session: AsyncSession, group_id: UUID, user_id: UUID) -> Any:
    group = await _group(session, group_id)
    if group.owner_id != user_id:
        raise GroupForbidden(group_id)
    return group


async def rename(session: AsyncSession, group_id: UUID, user_id: UUID, name: str) -> None:
    await _require_owner(session, group_id, user_id)
    await session.execute(
        update(groups_table)
        .where(groups_table.c.group_id == group_id)
        .values(name=_clean_name(name))
    )
    await session.commit()


async def remove_member(session: AsyncSession, group_id: UUID, owner: UUID, member: UUID) -> None:
    await _require_owner(session, group_id, owner)
    if member == owner:
        raise GroupError("Leave the group instead.")
    await session.execute(
        delete(members_table).where(
            members_table.c.group_id == group_id, members_table.c.user_id == member
        )
    )
    await session.commit()


async def rotate_code(session: AsyncSession, group_id: UUID, user_id: UUID) -> str:
    """A fresh invite code — the old link stops working."""
    await _require_owner(session, group_id, user_id)
    code = generate_invite_code(8)
    await session.execute(
        update(groups_table).where(groups_table.c.group_id == group_id).values(invite_code=code)
    )
    await session.commit()
    return code


async def delete_group(session: AsyncSession, group_id: UUID, user_id: UUID) -> None:
    await _require_owner(session, group_id, user_id)
    await _delete_group(session, group_id)
