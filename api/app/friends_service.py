"""Friend requests, the friend list, and who you might add next."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import Row, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import friendships as friendships_table
from .db import room_participants as room_participants_table
from .db import rooms as rooms_table
from .db import users as users_table
from .time import utcnow
from .users_service import UserProfile, profiles_for


class FriendEdge(BaseModel):
    """A friendship or pending request, described from the caller's side —
    `user` is always the other person, never you."""

    id: UUID
    user: UserProfile
    created_at: datetime


class FriendsResponse(BaseModel):
    friends: list[FriendEdge]
    #: Requests waiting on you to accept.
    incoming: list[FriendEdge]
    #: Requests you've sent that haven't been answered.
    outgoing: list[FriendEdge]


class FriendRequestError(Exception):
    pass


class FriendNotFound(Exception):
    pass


async def _edges_for(session: AsyncSession, player_id: UUID) -> Sequence[Row[Any]]:
    return (
        await session.execute(
            select(friendships_table).where(
                or_(
                    friendships_table.c.requester_id == player_id,
                    friendships_table.c.addressee_id == player_id,
                )
            )
        )
    ).all()


async def build_friends_for(session: AsyncSession, player_id: UUID) -> FriendsResponse:
    rows = await _edges_for(session, player_id)
    others = [r.addressee_id if r.requester_id == player_id else r.requester_id for r in rows]
    profiles = await profiles_for(session, others)

    friends: list[FriendEdge] = []
    incoming: list[FriendEdge] = []
    outgoing: list[FriendEdge] = []
    for r in rows:
        other_id = r.addressee_id if r.requester_id == player_id else r.requester_id
        profile = profiles.get(other_id)
        if profile is None:
            continue  # directory row vanished; nothing useful to show
        edge = FriendEdge(id=r.id, user=profile, created_at=r.created_at)
        if r.status == "accepted":
            friends.append(edge)
        elif r.requester_id == player_id:
            outgoing.append(edge)
        else:
            incoming.append(edge)

    friends.sort(key=lambda e: e.user.display_name.lower())
    incoming.sort(key=lambda e: e.created_at, reverse=True)
    outgoing.sort(key=lambda e: e.created_at, reverse=True)
    return FriendsResponse(friends=friends, incoming=incoming, outgoing=outgoing)


async def friend_ids(session: AsyncSession, player_id: UUID) -> set[UUID]:
    """Just the accepted set — used to gate access to a friend's stats."""
    rows = (
        await session.execute(
            select(friendships_table).where(
                friendships_table.c.status == "accepted",
                or_(
                    friendships_table.c.requester_id == player_id,
                    friendships_table.c.addressee_id == player_id,
                ),
            )
        )
    ).all()
    return {r.addressee_id if r.requester_id == player_id else r.requester_id for r in rows}


async def send_request(session: AsyncSession, requester: UUID, addressee: UUID) -> str:
    """Returns "pending", or "accepted" when this completes a mutual request.

    Two people who both tapped Add have already agreed; making the second one
    wait for an acceptance that logically already happened would be silly.
    """
    if requester == addressee:
        raise FriendRequestError("You can't add yourself.")
    exists = (
        await session.execute(
            select(users_table.c.user_id).where(users_table.c.user_id == addressee)
        )
    ).first()
    if exists is None:
        raise FriendNotFound(addressee)

    existing = (
        await session.execute(
            select(friendships_table).where(
                or_(
                    and_(
                        friendships_table.c.requester_id == requester,
                        friendships_table.c.addressee_id == addressee,
                    ),
                    and_(
                        friendships_table.c.requester_id == addressee,
                        friendships_table.c.addressee_id == requester,
                    ),
                )
            )
        )
    ).first()

    now = utcnow()
    if existing is not None:
        if existing.status == "accepted":
            raise FriendRequestError("You're already friends.")
        if existing.requester_id == requester:
            raise FriendRequestError("You've already sent them a request.")
        # They asked first — accept their request instead of opening a second.
        await session.execute(
            friendships_table.update()
            .where(friendships_table.c.id == existing.id)
            .values(status="accepted", responded_at=now)
        )
        await session.commit()
        return "accepted"

    await session.execute(
        friendships_table.insert().values(
            id=uuid4(),
            requester_id=requester,
            addressee_id=addressee,
            status="pending",
            created_at=now,
        )
    )
    await session.commit()
    return "pending"


async def accept_request(session: AsyncSession, edge_id: UUID, actor: UUID) -> None:
    row = (
        await session.execute(select(friendships_table).where(friendships_table.c.id == edge_id))
    ).first()
    # Only the person who was asked can accept, and only while it's pending.
    if row is None or row.addressee_id != actor or row.status != "pending":
        raise FriendNotFound(edge_id)
    await session.execute(
        friendships_table.update()
        .where(friendships_table.c.id == edge_id, friendships_table.c.status == "pending")
        .values(status="accepted", responded_at=utcnow())
    )
    await session.commit()


async def delete_edge(session: AsyncSession, edge_id: UUID, actor: UUID) -> None:
    """Decline, cancel, or unfriend — all of them just remove the row.

    Nothing records a refusal: the pair can try again later, and the app
    never has to tell anyone they were turned down.
    """
    row = (
        await session.execute(select(friendships_table).where(friendships_table.c.id == edge_id))
    ).first()
    if row is None or actor not in (row.requester_id, row.addressee_id):
        raise FriendNotFound(edge_id)
    await session.execute(friendships_table.delete().where(friendships_table.c.id == edge_id))
    await session.commit()


async def unfriend(session: AsyncSession, actor: UUID, other: UUID) -> None:
    row = (
        await session.execute(
            select(friendships_table).where(
                or_(
                    and_(
                        friendships_table.c.requester_id == actor,
                        friendships_table.c.addressee_id == other,
                    ),
                    and_(
                        friendships_table.c.requester_id == other,
                        friendships_table.c.addressee_id == actor,
                    ),
                )
            )
        )
    ).first()
    if row is None:
        raise FriendNotFound(other)
    await delete_edge(session, row.id, actor)


async def played_with(session: AsyncSession, player_id: UUID) -> list[UserProfile]:
    """People you've shared a room with who aren't friends (or pending) yet —
    the "add them from a game you played" path, which needs no lookup at all.
    """
    # Every room you've been in, as host or joiner.
    mine = (
        select(rooms_table.c.room_id)
        .where(rooms_table.c.host_id == player_id)
        .union(
            select(room_participants_table.c.room_id).where(
                room_participants_table.c.player_id == player_id
            )
        )
    )
    my_rooms = [r.room_id for r in (await session.execute(mine)).all()]
    if not my_rooms:
        return []

    hosts = select(rooms_table.c.host_id.label("pid")).where(rooms_table.c.room_id.in_(my_rooms))
    joiners = select(room_participants_table.c.player_id.label("pid")).where(
        room_participants_table.c.room_id.in_(my_rooms)
    )
    others = {
        r.pid for r in (await session.execute(hosts.union(joiners))).all() if r.pid != player_id
    }
    if not others:
        return []

    # Anyone already connected — friend or pending, either direction — is
    # not a suggestion.
    connected = {
        r.addressee_id if r.requester_id == player_id else r.requester_id
        for r in await _edges_for(session, player_id)
    }
    candidates = [pid for pid in others if pid not in connected]
    profiles = await profiles_for(session, candidates)
    return sorted(profiles.values(), key=lambda p: p.display_name.lower())
