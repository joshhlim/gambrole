"""GET /history/me — a player's past games, most-recent-first, with
settlement status per game. See history_service.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..history_service import build_history_for

router = APIRouter(prefix="/history", tags=["history"])


@router.get("/me")
async def get_my_history(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    history = await build_history_for(session, user.user_id)
    return history.model_dump(mode="json")
