"""Friends: the directory lookup, requests, and the friend list."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..friends_service import (
    FriendNotFound,
    FriendRequestError,
    accept_request,
    build_friends_for,
    delete_edge,
    played_with,
    send_request,
    unfriend,
)
from ..schemas import SendFriendRequest, SetUsernameRequest
from ..users_service import (
    USERNAME_HELP,
    USERNAME_RE,
    InvalidUsername,
    UsernameTaken,
    ensure_user,
    get_profile,
    search,
    set_username,
    username_taken,
)

router = APIRouter(tags=["friends"])


@router.get("/users/me")
async def me(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Also the directory's write point: opening the app is what records you
    in it, so this is where a new player becomes findable."""
    await ensure_user(session, user)
    profile = await get_profile(session, user.user_id)
    assert profile is not None  # ensure_user just wrote it
    return profile.model_dump(mode="json")


@router.put("/users/me/username")
async def put_username(
    body: SetUsernameRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    try:
        username = await set_username(session, user.user_id, body.username)
    except InvalidUsername as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except UsernameTaken as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return {"username": username}


@router.get("/users/username-available")
async def username_available(
    u: str = Query(min_length=1, max_length=24),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Is this handle free? Deliberately unauthenticated, because it runs on
    the sign-up form before an account exists — which is the only way to
    refuse a taken username *before* Supabase creates the account.

    It discloses nothing but yes/no: no owner, no name, no address. That a
    handle is taken is unavoidable knowledge in any system with unique
    usernames, and the authenticated search already answers it.
    """
    candidate = u.strip().lstrip("@").lower()
    if not USERNAME_RE.match(candidate):
        return {"available": False, "reason": USERNAME_HELP}
    taken = await username_taken(session, candidate)
    return {
        "available": not taken,
        "reason": f"@{candidate} is already taken." if taken else None,
        "username": candidate,
    }


@router.get("/users/search")
async def search_users(
    q: str = Query(min_length=1, max_length=320),
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Exact email or username only — see users_service.search."""
    results = await search(session, q, exclude=user.user_id)
    return {"results": [r.model_dump(mode="json") for r in results]}


@router.get("/friends")
async def list_friends(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    return (await build_friends_for(session, user.user_id)).model_dump(mode="json")


@router.get("/friends/suggestions")
async def suggestions(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    results = await played_with(session, user.user_id)
    return {"results": [r.model_dump(mode="json") for r in results]}


@router.post("/friends/requests", status_code=status.HTTP_201_CREATED)
async def create_request(
    body: SendFriendRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    try:
        outcome = await send_request(session, user.user_id, body.user_id)
    except FriendNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such player.") from e
    except FriendRequestError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return {"status": outcome}


@router.post("/friends/requests/{edge_id}/accept")
async def accept(
    edge_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await accept_request(session, edge_id, user.user_id)
    except FriendNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That request is no longer open.") from e
    return {"status": "accepted"}


@router.delete("/friends/requests/{edge_id}")
async def dismiss(
    edge_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Decline one you received, or cancel one you sent."""
    try:
        await delete_edge(session, edge_id, user.user_id)
    except FriendNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That request is no longer open.") from e
    return {"status": "removed"}


@router.delete("/friends/{other_id}")
async def remove_friend(
    other_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await unfriend(session, user.user_id, other_id)
    except FriendNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You aren't friends with them.") from e
    return {"status": "removed"}
