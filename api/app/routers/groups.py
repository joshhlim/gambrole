"""Groups — see group_service.py."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..group_service import (
    GroupError,
    GroupForbidden,
    GroupNotFound,
    create_group,
    delete_group,
    group_detail,
    join_by_code,
    leave,
    my_groups,
    remove_member,
    rename,
    rotate_code,
)
from ..ratelimit import rate_limit
from ..users_service import ensure_user

router = APIRouter(prefix="/groups", tags=["groups"])


class GroupNameRequest(BaseModel):
    name: str = Field(max_length=100)


def _raise(e: Exception) -> NoReturn:
    if isinstance(e, GroupNotFound):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found.") from e
    if isinstance(e, GroupForbidden):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't do that in this group.") from e
    raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


async def _detail(session: AsyncSession, group_id: UUID, user_id: UUID) -> dict[str, Any]:
    try:
        return (await group_detail(session, group_id, user_id)).model_dump(mode="json")
    except (GroupNotFound, GroupForbidden) as e:
        _raise(e)


@router.get("")
async def list_groups(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return {"groups": [g.model_dump(mode="json") for g in await my_groups(session, user.user_id)]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: GroupNameRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    try:
        group_id = await create_group(session, user.user_id, body.name)
    except GroupError as e:
        _raise(e)
    return await _detail(session, group_id, user.user_id)


@router.get("/{group_id}")
async def get_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _detail(session, group_id, user.user_id)


@router.post("/join/{code}", dependencies=[Depends(rate_limit("group-join", 30))])
async def join(
    code: str,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await ensure_user(session, user)
    try:
        group_id = await join_by_code(session, user.user_id, code)
    except (GroupNotFound, GroupError) as e:
        _raise(e)
    return await _detail(session, group_id, user.user_id)


@router.post("/{group_id}/leave")
async def leave_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await leave(session, group_id, user.user_id)
    except GroupNotFound as e:
        _raise(e)
    return {"left": True}


@router.patch("/{group_id}")
async def rename_group(
    group_id: UUID,
    body: GroupNameRequest,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await rename(session, group_id, user.user_id, body.name)
    except (GroupNotFound, GroupForbidden, GroupError) as e:
        _raise(e)
    return await _detail(session, group_id, user.user_id)


@router.delete("/{group_id}/members/{member_id}")
async def remove(
    group_id: UUID,
    member_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await remove_member(session, group_id, user.user_id, member_id)
    except (GroupNotFound, GroupForbidden, GroupError) as e:
        _raise(e)
    return await _detail(session, group_id, user.user_id)


@router.post("/{group_id}/invite-code")
async def new_invite_code(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await rotate_code(session, group_id, user.user_id)
    except (GroupNotFound, GroupForbidden) as e:
        _raise(e)
    return await _detail(session, group_id, user.user_id)


@router.delete("/{group_id}")
async def delete(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        await delete_group(session, group_id, user.user_id)
    except (GroupNotFound, GroupForbidden) as e:
        _raise(e)
    return {"deleted": True}
