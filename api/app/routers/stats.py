"""GET /stats/me — one combined analytics payload (overview + Taidi +
Mahjong sections), computed in a single pass. See stats_service.py and
ADR-0007.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..stats_service import build_stats_for

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/me")
async def get_my_stats(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    stats = await build_stats_for(session, user.user_id)
    return stats.model_dump(mode="json")
