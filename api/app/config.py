"""App settings, read from environment (prefix TAIDI_) or a local .env file."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAIDI_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://gambrole:gambrole_dev@localhost:5433/gambrole"

    # "dev": local HS256 tokens minted by POST /auth/dev-login, no external IdP needed.
    # "supabase": verify tokens issued by Supabase Auth instead.
    auth_mode: Literal["dev", "supabase"] = "dev"
    dev_jwt_secret: str = "dev-only-insecure-secret-change-me"
    access_token_ttl_minutes: int = 60 * 24 * 7  # a week — fine for a party-game app

    # Supabase projects sign tokens one of two ways, and a project only ever
    # exposes the values for whichever it uses:
    # - Newer projects: an asymmetric signing key, verified against a public
    #   JWKS endpoint derived from the project URL. Set supabase_url.
    # - Legacy projects: a shared HS256 secret, from Project Settings -> API
    #   -> "JWT Secret" / "Legacy JWT Secret". Set supabase_jwt_secret.
    # Both may be set; JWKS is tried first when present.
    supabase_url: str | None = None
    supabase_jwt_secret: str | None = None

    # :3000 is Next.js's default; :3100 is what this repo's local dev
    # and Playwright config use instead, since :3000 is often already
    # taken by an unrelated project on a shared dev machine.
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3100"]


settings = Settings()
