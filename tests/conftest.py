"""Shared fixtures: every test gets a throwaway local SQLite database."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

import db  # noqa: E402

APP_PATH = ROOT / "taidi.py"


# db.secret must never read from .streamlit/secrets.toml in tests:
# a developer's real Turso credentials there would point the suite (which
# wipes tables) at the production database. Tests control these via env only.
_ENV_ONLY_KEYS = {"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "APP_PASSCODE"}
_real_secret = db.secret


def _test_secret(key: str):
    if key in _ENV_ONLY_KEYS:
        return os.environ.get(key)
    return _real_secret(key)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Point db at a fresh file and make sure no cloud credentials leak in."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("APP_PASSCODE", raising=False)
    monkeypatch.setattr(db, "secret", _test_secret)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    yield


@pytest.fixture
def app_path():
    return str(APP_PATH)
