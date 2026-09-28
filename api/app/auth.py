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

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.types import Options

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
        _jwks_client = jwt.PyJWKClient(_jwks_url(), cache_keys=True, timeout=_JWKS_TIMEOUT_S)
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


# A token naming a key id we don't have forces a JWKS refetch — which is how
# a legitimate key rotation gets picked up, but also something anyone can
# trigger with made-up tokens. Refetch at most this often.
_JWKS_REFRESH_INTERVAL_S = 60.0
_JWKS_TIMEOUT_S = 5.0
_last_jwks_refresh = 0.0

# Every token must say who it's for and when it stops working.
_REQUIRED_CLAIMS: Options = {"require": ["exp", "sub"]}


async def _supabase_signing_key(token: str) -> Any:
    """The public key a Supabase token was signed with.

    PyJWKClient fetches over blocking HTTP; run on a worker thread so a slow
    or stalled fetch can't freeze every other request on the event loop.
    """
    global _last_jwks_refresh
    kid = jwt.get_unverified_header(token).get("kid")
    client = _get_jwks_client()
    keys = await run_in_threadpool(client.get_signing_keys)
    match = next((k for k in keys if k.key_id == kid), None)
    now = time.monotonic()
    if match is None and now - _last_jwks_refresh >= _JWKS_REFRESH_INTERVAL_S:
        _last_jwks_refresh = now
        keys = await run_in_threadpool(client.get_signing_keys, True)
        match = next((k for k in keys if k.key_id == kid), None)
    if match is None:
        raise jwt.InvalidTokenError("Unknown signing key.")
    return match.key


async def _decode(token: str) -> dict[str, Any]:
    if settings.auth_mode == "dev":
        try:
            # Dev tokens carry no audience claim — nothing to check.
            return jwt.decode(
                token,
                settings.dev_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False, "require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e
    if settings.auth_mode != "supabase":
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Auth mode is not configured.")

    # supabase mode. Every access token carries aud="authenticated" —
    # verifying it rejects, e.g., a service-role token being mistakenly
    # used as a user's bearer token.
    try:
        if settings.supabase_url:
            return jwt.decode(
                token,
                await _supabase_signing_key(token),
                algorithms=_SUPABASE_JWT_ALGORITHMS,
                audience="authenticated",
                options=_REQUIRED_CLAIMS,
            )
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options=_REQUIRED_CLAIMS,
            )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Supabase auth is not configured (set TAIDI_SUPABASE_URL or TAIDI_SUPABASE_JWT_SECRET).",
        )
    except jwt.PyJWKClientConnectionError as e:  # pragma: no cover — network
        # Checked first: it's a PyJWTError too, but the token isn't the
        # problem — Supabase's key endpoint didn't answer.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Couldn't verify sign-in right now."
        ) from e
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e


def _email_from_claims(claims: dict[str, Any]) -> str | None:
    email = claims.get("email")
    return str(email).strip().lower() if email else None


# users.display_name's width. The name comes from user-editable metadata,
# so an over-long one must be trimmed here rather than fail every insert.
MAX_DISPLAY_NAME = 100


def _display_name_from_claims(claims: dict[str, Any]) -> str:
    if settings.auth_mode == "dev":
        name = claims.get("display_name")
    else:
        # Supabase's default claims don't carry a display name unless the
        # client set one in user_metadata at sign-up. Never fall back to
        # the email address: display names are shown to everyone at the
        # table and in search, and addresses are meant to stay private.
        name = (claims.get("user_metadata") or {}).get("display_name")
    name = " ".join(str(name or "").split())[:MAX_DISPLAY_NAME]
    return name or "Player"


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token.")
    claims = await _decode(creds.credentials)
    try:
        user_id = UUID(str(claims["sub"]))
    except ValueError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject.") from e
    return CurrentUser(
        user_id=user_id,
        display_name=_display_name_from_claims(claims),
        email=_email_from_claims(claims),
    )
