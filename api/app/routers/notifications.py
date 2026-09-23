"""GET /notifications — everything waiting on you, in one request."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..notifications_service import build_notifications_for

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def my_notifications(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return (await build_notifications_for(session, user.user_id)).model_dump(mode="json")
