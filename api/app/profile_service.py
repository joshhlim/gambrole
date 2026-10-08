"""Profiles, per-account preferences and privacy.

Profile photos are stored in the database (db.user_avatars) and served by
/avatars/{user_id}. An <img> tag can't send a bearer token, so instead of
authenticating the request, the URL carries a signature only this API can
make — and the API only hands URLs out where it's already decided the
viewer may see that person (in a game, a friends list, a profile page).
The version in the URL changes with every new photo, so caches can keep
one forever.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, Literal
from uuid import UUID

from mahjong_core.models import MahjongRules
from pydantic import BaseModel, Field, ValidationError, field_validator
from taidi_core.models import GameRules

from .config import settings

# Named rather than free hex so every one has a version tuned for both
# themes in the web app's palette.
ACCENTS = ("jade", "gold", "ruby", "sapphire", "amethyst", "slate", "coral", "teal")

# Display only — no conversion. Covers the places these games are played.
CURRENCY_SYMBOLS = ("$", "S$", "RM", "HK$", "NT$", "A$", "US$", "£", "€", "¥")

Visibility = Literal["everyone", "friends", "nobody"]
StatsVisibility = Literal["friends", "nobody"]

MAX_AVATAR_BYTES = 256 * 1024
# What the client's resize produces, recognised by magic bytes rather than
# trusting the Content-Type header.
_IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}

# Signs avatar URLs. Configured so links survive restarts; without it a
# per-process key still works, links just change when the API restarts.
_ASSET_KEY = (settings.asset_secret or secrets.token_hex(32)).encode()


def _sign(user_id: UUID, version: int) -> str:
    message = f"{user_id}:{version}".encode()
    return hmac.new(_ASSET_KEY, message, hashlib.sha256).hexdigest()[:32]


def avatar_url(user_id: UUID, version: int | None) -> str | None:
    """Relative to the API's base URL. None when there's no photo."""
    if version is None:
        return None
    return f"/avatars/{user_id}?v={version}&sig={_sign(user_id, version)}"


def valid_avatar_signature(user_id: UUID, version: int, sig: str) -> bool:
    return hmac.compare_digest(_sign(user_id, version), sig)


def sniff_image(data: bytes) -> str | None:
    """The image's real type, or None if it isn't one we accept."""
    for content_type, prefixes in _IMAGE_SIGNATURES.items():
        if any(data.startswith(p) for p in prefixes):
            if content_type == "image/webp" and data[8:12] != b"WEBP":
                continue
            return content_type
    return None


class Preferences(BaseModel):
    """Stored whole in users.preferences. Every field optional so an older
    row (or a partial update) is always valid."""

    theme: Literal["system", "light", "dark"] = "system"
    # Set once the first-run walkthrough has been seen or skipped.
    onboarded: bool = False
    currency_symbol: str = "$"
    # Rules /new starts from, per game — a rules object as /rooms accepts it.
    default_rules: dict[Literal["taidi", "mahjong"], dict[str, Any]] = Field(default_factory=dict)

    @field_validator("currency_symbol")
    @classmethod
    def _known_symbol(cls, value: str) -> str:
        if value not in CURRENCY_SYMBOLS:
            raise ValueError(f"Currency symbol must be one of {', '.join(CURRENCY_SYMBOLS)}.")
        return value

    @field_validator("default_rules")
    @classmethod
    def _valid_rules(cls, value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        # Normalised through the same models a room's rules go through, so a
        # saved default can never be one the API would refuse at creation.
        normalised: dict[str, dict[str, Any]] = {}
        for game, raw in value.items():
            try:
                rules = (
                    MahjongRules.from_stored(raw)
                    if game == "mahjong"
                    else GameRules.model_validate(raw)
                )
            except ValidationError as e:
                raise ValueError(f"Invalid {game} rules: {e.errors()[0]['msg']}") from e
            normalised[game] = rules.model_dump(mode="json")
        return normalised


def read_preferences(raw: dict[str, Any] | None) -> Preferences:
    """Stored preferences, tolerating anything stale in the row."""
    try:
        return Preferences.model_validate(raw or {})
    except ValidationError:
        return Preferences()
