"""GET /debts/me plus the mark-paid/approve/reject actions. See
debts_service.py.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import CurrentUser, get_current_user
from ..db import get_session
from ..debts_service import (
    SettlementForbidden,
    SettlementInvalidTransition,
    SettlementNotFound,
    approve,
    build_debts_for,
    mark_paid,
    reject,
)

router = APIRouter(prefix="/debts", tags=["debts"])


@router.get("/me")
async def get_my_debts(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    debts = await build_debts_for(session, user.user_id)
    return debts.model_dump(mode="json")


@router.post("/{settlement_id}/mark-paid")
async def mark_paid_route(
    settlement_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await mark_paid(session, settlement_id, user.user_id)
    except SettlementNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Debt not found.") from e
    except SettlementForbidden as e:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the person who owes this debt can mark it paid."
        ) from e
    except SettlementInvalidTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return result.model_dump(mode="json")


@router.post("/{settlement_id}/approve")
async def approve_route(
    settlement_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await approve(session, settlement_id, user.user_id)
    except SettlementNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Debt not found.") from e
    except SettlementForbidden as e:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the person owed this debt can approve it."
        ) from e
    except SettlementInvalidTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return result.model_dump(mode="json")


@router.post("/{settlement_id}/reject")
async def reject_route(
    settlement_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        result = await reject(session, settlement_id, user.user_id)
    except SettlementNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Debt not found.") from e
    except SettlementForbidden as e:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the person owed this debt can reject it."
        ) from e
    except SettlementInvalidTransition as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return result.model_dump(mode="json")
