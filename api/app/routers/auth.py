"""Dev-mode login. Only meaningful when TAIDI_AUTH_MODE=dev —
mints a token for any display name with no external identity provider.
Disabled (404) when the app is running against real Supabase auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import MAX_DISPLAY_NAME, mint_dev_token
from ..config import settings
from ..ratelimit import rate_limit

router = APIRouter(prefix="/auth", tags=["auth"])


class DevLoginRequest(BaseModel):
    display_name: str = Field(max_length=MAX_DISPLAY_NAME)


class DevLoginResponse(BaseModel):
    access_token: str
    user_id: str
    display_name: str


@router.post(
    "/dev-login",
    response_model=DevLoginResponse,
    dependencies=[Depends(rate_limit("dev-login", 30))],
)
def dev_login(body: DevLoginRequest) -> DevLoginResponse:
    if settings.auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dev login is disabled in this environment.")
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "display_name is required.")
    token, uid = mint_dev_token(name)
    return DevLoginResponse(access_token=token, user_id=str(uid), display_name=name)
