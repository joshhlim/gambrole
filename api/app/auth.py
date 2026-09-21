"""Authentication: a pluggable JWT verifier plus a dev-only token minter.

Both auth modes produce the same thing — a CurrentUser(user_id, display_name)
— so the rest of the app never needs to know which mode is active. In "dev"
mode, POST /auth/dev-login mints a token for any display name, no external
identity provider needed; that's what local development and tests use. In
"supabase" mode, tokens are verified against the real Supabase project
instead, and nothing else changes.

Supabase signs tokens one of two ways depending on when the project was
created, and only ever exposes the matching value in its dashboard:
- Newer projects: an asymmetric signing key. Verified against the
  project's public JWKS endpoint (no shared secret involved at all) —
  set TAIDI_SUPABASE_URL.
- Legacy projects: a shared HS256 secret. Set TAIDI_SUPABASE_JWT_SECRET.
JWKS is tried first when supabase_url is configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .time import utcnow

_bearer = HTTPBearer(auto_error=False)

# Supabase's asymmetric signing keys can be ES256 or RS256 depending on the
# project's configuration; accepting both avoids needing to know which in
# advance. Built lazily (not at import time) so tests can point it at a
# different URL, and cached because it fetches the real JWKS over HTTP.
_SUPABASE_JWT_ALGORITHMS = ["ES256", "RS256"]
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None or _jwks_client.uri != _jwks_url():
        _jwks_client = jwt.PyJWKClient(_jwks_url(), cache_keys=True)
    return _jwks_client


def _jwks_url() -> str:
    assert settings.supabase_url is not None
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@dataclass(frozen=True)
class CurrentUser:
    user_id: UUID
    display_name: str
    # Present in Supabase mode, where it's how one player finds another
    # (see users.email). Dev tokens carry no address, so it's None there.
    email: str | None = None


def mint_dev_token(display_name: str, user_id: UUID | None = None) -> tuple[str, UUID]:
    """Dev-mode only: mint a token for a fresh (or given) user id."""
    uid = user_id or uuid4()
    payload = {
        "sub": str(uid),
        "display_name": display_name,
        "exp": utcnow() + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    token = jwt.encode(payload, settings.dev_jwt_secret, algorithm="HS256")
    return token, uid


def _decode(token: str) -> dict[str, Any]:
    if settings.auth_mode == "dev":
        try:
            # Dev tokens carry no audience claim — nothing to check.
            return jwt.decode(
                token, settings.dev_jwt_secret, algorithms=["HS256"], options={"verify_aud": False}
            )
        except jwt.PyJWTError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e

    # supabase mode. Every access token carries aud="authenticated" —
    # verifying it rejects, e.g., a service-role token being mistakenly
    # used as a user's bearer token.
    try:
        if settings.supabase_url:
            signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=_SUPABASE_JWT_ALGORITHMS,
                audience="authenticated",
            )
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
            )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Supabase auth is not configured (set TAIDI_SUPABASE_URL or TAIDI_SUPABASE_JWT_SECRET).",
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e


def _email_from_claims(claims: dict[str, Any]) -> str | None:
    email = claims.get("email")
    return str(email).strip().lower() if email else None


def _display_name_from_claims(claims: dict[str, Any]) -> str:
    if settings.auth_mode == "dev":
        return str(claims.get("display_name", "Player"))
    # Supabase's default claims don't carry a display name unless the
    # client set one in user_metadata at sign-up.
    meta = claims.get("user_metadata") or {}
    name = meta.get("display_name") or claims.get("email") or "Player"
    return str(name)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    claims = _decode(creds.credentials)
    return CurrentUser(
        user_id=UUID(claims["sub"]),
        display_name=_display_name_from_claims(claims),
        email=_email_from_claims(claims),
    )
