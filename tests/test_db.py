"""Persistence: CRUD, rename propagation, backup round-trip, both drivers."""

import pytest

import db
from game import CardGameTracker, GameRules


def _seed_game():
    t = CardGameTracker(["Alice", "Bob"], GameRules())
    t.play_round([0, 5])
    return t


def test_player_crud_is_case_insensitive():
    pid1 = db.player_add("Alice")
    assert db.player_add("alice ") == pid1
    db.player_add("Bob")
    assert db.player_names() == ["Alice", "Bob"]
    assert db.player_delete("BOB") is True
    assert db.player_delete("nobody") is False
    assert db.player_names() == ["Alice"]


def test_active_and_archived_games():
    t = _seed_game()
    db.game_save("g1", {"tracker": t.to_snapshot(), "round_num": 2})
    assert db.game_load("g1")["round_num"] == 2
    assert db.games_all()[0]["game_id"] == "g1"
    assert db.names_in_active_games() == {"Alice", "Bob"}
    db.game_delete("g1")
    assert db.game_load("g1") is None

    aid = db.archive_add({"created_at": "2026-01-01 10:00:00", "final_totals": {"Alice": 1.0}})
    assert len(db.archive_all()) == 1
    db.archive_delete(aid)
    assert db.archive_all() == []


def test_settings_and_rulesets():
    db.settings_set("default_rules", GameRules(card_value=0.5).to_dict())
    assert GameRules.from_dict(db.settings_get("default_rules")).card_value == 0.5
    db.ruleset_save("Casual", {"card_value": 0.1})
    assert db.rulesets_all()["Casual"]["card_value"] == 0.1
    db.ruleset_delete("Casual")
    assert db.rulesets_all() == {}


def test_rename_propagates_to_all_games():
    db.player_add("Alice")
    db.player_add("Bob")
    t = _seed_game()
    db.game_save("g1", {"tracker": t.to_snapshot(), "round_num": 2})
    db.archive_add(
        {
            "archive_id": "a1",
            "created_at": "2026-01-01 10:00:00",
            "players": t.players,
            "final_totals": {p: float(v) for p, v in t.balances.items()},
            "history": t.history.to_dict(orient="split"),
            "tx_log": t.tx_log,
        }
    )

    ok, err = db.rename_player("Alice", "Alicia")
    assert ok, err
    assert db.player_names() == ["Alicia", "Bob"]
    entry = db.archive_all()[0]
    assert "Alicia" in entry["final_totals"] and "Alice" not in entry["final_totals"]
    assert entry["players"] == ["Alicia", "Bob"]
    assert entry["history"]["index"] == ["Alicia", "Bob"]
    assert entry["tx_log"][0]["winner"] == "Alicia"
    active = db.game_load("g1")["tracker"]
    assert "Alicia" in active["balances"] and active["players"] == ["Alicia", "Bob"]

    assert db.rename_player("Bob", "alicia") == (False, "A player named 'alicia' already exists.")
    assert db.rename_player("Ghost", "X")[0] is False


def test_backup_export_import_round_trip():
    db.player_add("Alice")
    db.player_add("Bob")
    t = _seed_game()
    db.game_save("g1", {"tracker": t.to_snapshot(), "round_num": 2})
    db.archive_add(
        {
            "archive_id": "a1",
            "created_at": "2026-01-01 10:00:00",
            "final_totals": {"Alice": 1.0, "Bob": -1.0},
        }
    )
    db.settings_set("default_rules", {"card_value": 0.3})
    db.ruleset_save("Casual", {"card_value": 0.1})

    backup = db.export_all()
    db.factory_reset()
    assert db.player_names() == [] and db.archive_all() == []

    db.import_all(backup)
    assert db.player_names() == ["Alice", "Bob"]
    assert db.game_load("g1")["round_num"] == 2
    assert db.archive_all()[0]["archive_id"] == "a1"
    assert db.settings_get("default_rules") == {"card_value": 0.3}
    assert db.rulesets_all() == {"Casual": {"card_value": 0.1}}
    assert db.export_all()["players"] == backup["players"]


def test_import_rejects_unknown_version():
    with pytest.raises(ValueError):
        db.import_all({"version": 999})


def test_libsql_driver_backend(tmp_path, monkeypatch):
    """The Turso driver path (what the cloud uses), exercised against a local file."""
    pytest.importorskip("libsql")
    monkeypatch.setenv("TURSO_DATABASE_URL", str(tmp_path / "turso_local.db"))
    db.init_db()
    db.player_add("Alice")
    assert db.player_names() == ["Alice"]
    db.game_save("g1", {"tracker": _seed_game().to_snapshot(), "round_num": 2})
    assert db.games_all()[0]["game_id"] == "g1"
    assert db.rename_player("Alice", "Alicia")[0] is True
    assert "Alicia" in db.game_load("g1")["tracker"]["balances"]
    db.factory_reset()
    assert db.player_names() == []


def test_refuses_remote_turso_under_pytest(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://example.turso.io")
    with pytest.raises(RuntimeError, match="Turso"):
        db.player_names()
