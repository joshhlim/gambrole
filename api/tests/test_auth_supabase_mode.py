"""Verifies the supabase-mode JWT path against realistically-shaped tokens,
without needing a real Supabase project. See auth.py's module docstring —
dev and supabase modes share everything downstream of get_current_user, and
Supabase projects use one of two signing schemes depending on when they were
created (legacy shared secret, or a newer asymmetric key verified via JWKS)
— both are covered here."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import app.auth as auth_module
import jwt
import pytest
from app.auth import _decode, _display_name_from_claims, get_current_user
from app.config import settings
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

TEST_SECRET = "test-supabase-secret-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _supabase_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    monkeypatch.setattr(settings, "supabase_url", None)
    yield


def _supabase_claims(**overrides) -> dict:
    claims = {
        "sub": str(uuid4()),
        "aud": "authenticated",
        "role": "authenticated",
        "email": "alice@example.com",
        "user_metadata": {"display_name": "Alice"},
        "app_metadata": {"provider": "email"},
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "iat": datetime.now(UTC),
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict, secret: str = TEST_SECRET) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


async def test_valid_supabase_token_decodes_with_display_name():
    claims = _supabase_claims()
    decoded = await _decode(_sign(claims))
    assert decoded["sub"] == claims["sub"]
    assert _display_name_from_claims(decoded) == "Alice"


async def test_never_falls_back_to_the_email_address_for_a_name():
    # Display names are shown to everyone at the table; addresses are private.
    claims = _supabase_claims(user_metadata={})
    decoded = await _decode(_sign(claims))
    assert _display_name_from_claims(decoded) == "Player"


async def test_overlong_display_name_is_trimmed_not_fatal():
    claims = _supabase_claims(user_metadata={"display_name": "x" * 500})
    decoded = await _decode(_sign(claims))
    assert len(_display_name_from_claims(decoded)) == 100


@pytest.mark.parametrize("missing", ["exp", "sub"])
async def test_token_missing_a_required_claim_is_rejected(missing):
    claims = _supabase_claims()
    del claims[missing]
    with pytest.raises(HTTPException) as exc:
        await _decode(_sign(claims))
    assert exc.value.status_code == 401


async def test_non_uuid_subject_is_a_401_not_a_crash():
    creds = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=_sign(_supabase_claims(sub="nope"))
    )
    with pytest.raises(HTTPException) as exc:
        await get_current_user(creds)
    assert exc.value.status_code == 401


async def test_wrong_audience_is_rejected():
    claims = _supabase_claims(aud="anon")
    with pytest.raises(Exception):  # noqa: B017 - HTTPException, imported lazily by auth.py
        await _decode(_sign(claims))


async def test_wrong_secret_is_rejected():
    claims = _supabase_claims()
    with pytest.raises(Exception):  # noqa: B017
        await _decode(_sign(claims, secret="a-completely-different-secret-value"))


async def test_expired_token_is_rejected():
    claims = _supabase_claims(exp=datetime.now(UTC) - timedelta(minutes=1))
    with pytest.raises(Exception):  # noqa: B017
        await _decode(_sign(claims))


# ============== JWKS mode (newer Supabase projects) ==============
#
# Newer Supabase projects sign with an asymmetric key instead of a shared
# secret, verified against a public JWKS endpoint. Real network access isn't
# needed to prove this works — PyJWKClient.fetch_data is monkeypatched to
# return a JWKS built from a real, freshly generated EC keypair.

TEST_KID = "test-key-1"


@pytest.fixture
def ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def jwks_mode(monkeypatch, ec_keypair):
    """Switches the autouse _supabase_mode fixture's config to JWKS mode and
    makes any PyJWKClient this test creates serve our test keypair instead
    of fetching a real JWKS over the network."""
    _private_key, public_key = ec_keypair
    monkeypatch.setattr(settings, "supabase_url", "https://fake-project.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", None)
    monkeypatch.setattr(auth_module, "_jwks_client", None)

    alg = jwt.algorithms.get_default_algorithms()["ES256"]
    jwk_dict = alg.to_jwk(public_key, as_dict=True)
    jwk_dict.update(kid=TEST_KID, alg="ES256", use="sig")
    fake_jwks = {"keys": [jwk_dict]}
    fetches: list[int] = []

    def fetch_data(self):
        # Like the real one, fill the key-set cache on a successful fetch.
        fetches.append(1)
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(fake_jwks)
        return fake_jwks

    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setattr(auth_module, "_last_jwks_refresh", 0.0)
    return fetches


def _sign_asymmetric(claims: dict, private_key) -> str:
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": TEST_KID})


async def test_jwks_mode_valid_token_decodes(jwks_mode, ec_keypair):
    private_key, _ = ec_keypair
    claims = _supabase_claims()
    decoded = await _decode(_sign_asymmetric(claims, private_key))
    assert decoded["sub"] == claims["sub"]
    assert _display_name_from_claims(decoded) == "Alice"


async def test_jwks_mode_token_signed_by_a_different_key_is_rejected(jwks_mode, ec_keypair):
    other_private_key = ec.generate_private_key(ec.SECP256R1())
    claims = _supabase_claims()
    with pytest.raises(Exception):  # noqa: B017
        await _decode(_sign_asymmetric(claims, other_private_key))


async def test_jwks_mode_wrong_audience_is_rejected(jwks_mode, ec_keypair):
    private_key, _ = ec_keypair
    claims = _supabase_claims(aud="anon")
    with pytest.raises(Exception):  # noqa: B017
        await _decode(_sign_asymmetric(claims, private_key))


async def test_jwks_preferred_over_legacy_secret_when_both_configured(
    monkeypatch, jwks_mode, ec_keypair
):
    # supabase_jwt_secret set alongside supabase_url — JWKS must win, not
    # silently fall back to (or require) the legacy secret.
    monkeypatch.setattr(settings, "supabase_jwt_secret", TEST_SECRET)
    private_key, _ = ec_keypair
    claims = _supabase_claims()
    decoded = await _decode(_sign_asymmetric(claims, private_key))
    assert decoded["sub"] == claims["sub"]


async def test_neither_jwks_nor_secret_configured_raises_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "supabase_jwt_secret", None)
    with pytest.raises(Exception):  # noqa: B017
        await _decode(_sign(_supabase_claims()))


async def test_jwks_unknown_key_ids_cant_force_a_refetch_every_request(jwks_mode, ec_keypair):
    """Made-up key ids used to trigger a blocking JWKS fetch per request —
    a way for anyone to stall the server. Now at most one per interval."""
    private_key, _ = ec_keypair
    for i in range(5):
        token = jwt.encode(
            _supabase_claims(), private_key, algorithm="ES256", headers={"kid": f"bogus-{i}"}
        )
        with pytest.raises(HTTPException) as exc:
            await _decode(token)
        assert exc.value.status_code == 401
    # The first lookup fetches the key set; one forced refresh is allowed
    # for the first unknown kid; every later one is refused from cache.
    assert len(jwks_mode) == 2
