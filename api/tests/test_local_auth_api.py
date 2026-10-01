"""TAIDI_AUTH_MODE=local: email + password accounts in the plain-text
test_accounts table, with no Supabase involved (see routers/local_auth.py)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.auth import mint_dev_token
from app.config import settings
from app.db import engine
from app.db import test_accounts as accounts_table
from app.main import app, lifespan
from app.time import utcnow
from sqlalchemy import select, update

SECRET = "local-mode-test-secret-at-least-32-chars"


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "local_jwt_secret", SECRET)


async def _signup(client, email="alice@example.com", password="hunter22", name="Alice"):
    r = await client.post(
        "/auth/local/signup", json={"email": email, "password": password, "display_name": name}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


async def _row(email: str):
    async with engine.connect() as conn:
        return (
            await conn.execute(select(accounts_table).where(accounts_table.c.email == email))
        ).first()


async def test_signup_stores_the_account_as_typed_and_signs_you_in(client, local_mode):
    session = await _signup(client, email="  Alice@Example.com ")
    row = await _row("alice@example.com")
    assert row.password == "hunter22"
    assert row.display_name == "Alice"

    me = await client.get("/users/me", headers=_bearer(session))
    assert me.status_code == 200, me.text
    assert me.json()["display_name"] == "Alice"
    assert me.json()["email"] == "alice@example.com"


async def test_a_local_session_can_play(client, local_mode):
    session = await _signup(client)
    r = await client.post("/rooms", headers=_bearer(session))
    assert r.status_code == 201, r.text


async def test_duplicate_email_is_refused(client, local_mode):
    await _signup(client)
    r = await client.post(
        "/auth/local/signup",
        json={"email": "alice@example.com", "password": "another1", "display_name": "A2"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "User already registered"


async def test_short_password_is_refused(client, local_mode):
    r = await client.post(
        "/auth/local/signup",
        json={"email": "a@b.co", "password": "12345", "display_name": "A"},
    )
    assert r.status_code == 400


async def test_login(client, local_mode):
    await _signup(client)
    bad = await client.post(
        "/auth/local/login", json={"email": "alice@example.com", "password": "wrong"}
    )
    assert bad.status_code == 400 and bad.json()["detail"] == "Invalid login credentials"
    nobody = await client.post(
        "/auth/local/login", json={"email": "nobody@example.com", "password": "hunter22"}
    )
    assert nobody.status_code == 400
    good = await client.post(
        "/auth/local/login", json={"email": "ALICE@example.com", "password": "hunter22"}
    )
    assert good.status_code == 200, good.text


async def test_password_reset_round_trip(client, local_mode):
    await _signup(client)
    r = await client.post(
        "/auth/local/password-reset",
        json={"email": "alice@example.com", "redirect_to": "http://localhost:3100/auth/callback"},
    )
    assert r.status_code == 204
    token = (await _row("alice@example.com")).reset_token
    assert token

    r = await client.post(
        "/auth/local/password-reset/confirm", json={"token": token, "password": "newpass1"}
    )
    assert r.status_code == 200, r.text
    row = await _row("alice@example.com")
    assert row.password == "newpass1" and row.reset_token is None

    # Used once only.
    again = await client.post(
        "/auth/local/password-reset/confirm", json={"token": token, "password": "newpass2"}
    )
    assert again.status_code == 400


async def test_reset_for_an_unknown_address_looks_the_same(client, local_mode):
    r = await client.post("/auth/local/password-reset", json={"email": "nobody@example.com"})
    assert r.status_code == 204


async def test_expired_reset_link_is_refused(client, local_mode):
    await _signup(client)
    await client.post("/auth/local/password-reset", json={"email": "alice@example.com"})
    async with engine.begin() as conn:
        await conn.execute(
            update(accounts_table).values(reset_expires_at=utcnow() - timedelta(minutes=1))
        )
    token = (await _row("alice@example.com")).reset_token
    r = await client.post(
        "/auth/local/password-reset/confirm", json={"token": token, "password": "newpass1"}
    )
    assert r.status_code == 400


async def test_settings_changes_update_the_table_and_the_token(client, local_mode):
    session = await _signup(client)
    await _signup(client, email="bob@example.com", name="Bob")

    r = await client.patch(
        "/auth/local/me",
        headers=_bearer(session),
        json={"display_name": "Alicia", "email": "alicia@example.com", "password": "changed1"},
    )
    assert r.status_code == 200, r.text
    fresh = r.json()
    assert fresh["display_name"] == "Alicia" and fresh["email"] == "alicia@example.com"
    row = await _row("alicia@example.com")
    assert row.password == "changed1"
    me = (await client.get("/users/me", headers=_bearer(fresh))).json()
    assert me["display_name"] == "Alicia" and me["email"] == "alicia@example.com"

    taken = await client.patch(
        "/auth/local/me", headers=_bearer(fresh), json={"email": "bob@example.com"}
    )
    assert taken.status_code == 400


async def test_local_endpoints_dont_exist_in_other_modes(client):
    r = await client.post(
        "/auth/local/signup", json={"email": "a@b.co", "password": "123456", "display_name": "A"}
    )
    assert r.status_code == 404


async def test_a_dev_token_isnt_accepted_in_local_mode(client, local_mode):
    token, _uid = mint_dev_token("Mallory")
    r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_local_mode_refuses_to_start_without_a_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "local_jwt_secret", None)
    with pytest.raises(RuntimeError):
        async with lifespan(app):
            pass
