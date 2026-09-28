"""Persistence for Taidi Tracker.

Two backends, picked automatically per connection:
- Local SQLite file (taidi.db next to the app) — the default for development.
- Turso (hosted libSQL) — used when TURSO_DATABASE_URL is present in
  Streamlit secrets or the environment, so data survives cloud redeploys.

Both speak the same SQL; rows are accessed positionally so the two drivers
behave identically.
"""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

DB_PATH = Path(__file__).parent / "taidi.db"


def secret(key: str):
    """Read a setting from Streamlit secrets, falling back to the environment."""
    try:
        import streamlit as st

        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key)


def _connect_raw():
    url = secret("TURSO_DATABASE_URL")
    if url:
        # Tests wipe tables freely; never let that reach a hosted database
        # (st.secrets would otherwise load .streamlit/secrets.toml). A local
        # file path is fine — the libsql driver test uses one.
        if "pytest" in sys.modules and "://" in str(url):
            raise RuntimeError("Refusing to connect to remote Turso under pytest")
        import libsql

        token = secret("TURSO_AUTH_TOKEN")
        kwargs = {"auth_token": token} if token else {}
        return libsql.connect(url, **kwargs)
    return sqlite3.connect(DB_PATH)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def _conn():
    conn = _connect_raw()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_TABLES = [
    """CREATE TABLE IF NOT EXISTS players (
        player_id  TEXT PRIMARY KEY,
        name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS archived_games (
        archive_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        data       TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS active_games (
        game_id    TEXT PRIMARY KEY,
        updated_at TEXT NOT NULL,
        data       TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rulesets (
        name TEXT PRIMARY KEY COLLATE NOCASE,
        data TEXT NOT NULL
    )""",
]


def init_db():
    with _conn() as c:
        for ddl in _TABLES:
            c.execute(ddl)


# ============== Players ==============


def player_add(name: str) -> str:
    """Add a player (case-insensitive dedupe). Returns the player id."""
    name_clean = name.strip()
    if not name_clean:
        return ""
    with _conn() as c:
        row = c.execute(
            "SELECT player_id FROM players WHERE name = ? COLLATE NOCASE", (name_clean,)
        ).fetchone()
        if row:
            return row[0]
        pid = str(uuid4())
        c.execute(
            "INSERT INTO players (player_id, name, created_at) VALUES (?, ?, ?)",
            (pid, name_clean, _now()),
        )
        return pid


def player_delete(name: str) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT player_id FROM players WHERE name = ? COLLATE NOCASE", (name.strip(),)
        ).fetchone()
        if row is None:
            return False
        c.execute("DELETE FROM players WHERE player_id = ?", (row[0],))
        return True


def player_names() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT name FROM players ORDER BY name COLLATE NOCASE").fetchall()
        return [r[0] for r in rows]


def players_clear():
    with _conn() as c:
        c.execute("DELETE FROM players")


# ============== Archived (finished) games ==============


def archive_add(entry: dict) -> str:
    archive_id = entry.get("archive_id") or str(uuid4())
    entry["archive_id"] = archive_id
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO archived_games (archive_id, created_at, data) VALUES (?, ?, ?)",
            (archive_id, entry.get("created_at", _now()), json.dumps(entry)),
        )
    return archive_id


def archive_all() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM archived_games ORDER BY created_at DESC").fetchall()
        return [json.loads(r[0]) for r in rows]


def archive_delete(archive_id: str):
    with _conn() as c:
        c.execute("DELETE FROM archived_games WHERE archive_id = ?", (archive_id,))


def archive_clear():
    with _conn() as c:
        c.execute("DELETE FROM archived_games")


# ============== Active (unfinished) games ==============


def game_save(game_id: str, snapshot: dict):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO active_games (game_id, updated_at, data) VALUES (?, ?, ?)",
            (game_id, _now(), json.dumps(snapshot)),
        )


def game_load(game_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM active_games WHERE game_id = ?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None


def game_delete(game_id: str):
    with _conn() as c:
        c.execute("DELETE FROM active_games WHERE game_id = ?", (game_id,))


def games_all() -> list[dict]:
    """All unfinished games, most recently played first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT game_id, updated_at, data FROM active_games ORDER BY updated_at DESC"
        ).fetchall()
        return [{"game_id": r[0], "updated_at": r[1], "data": json.loads(r[2])} for r in rows]


def names_in_active_games() -> set[str]:
    return {p for g in games_all() for p in g["data"].get("tracker", {}).get("players", [])}


# ============== Player rename (propagates everywhere) ==============


def _rename_in_game_dict(d: dict, old: str, new: str) -> bool:
    """Rename a player inside one game dict (archive entry or tracker snapshot)."""
    changed = False
    if old in d.get("players", []):
        d["players"] = [new if p == old else p for p in d["players"]]
        changed = True
    for key in ("balances", "final_totals"):
        if key in d and old in d[key]:
            d[key][new] = d[key].pop(old)
            changed = True
    hist = d.get("history")
    if hist and old in hist.get("index", []):
        hist["index"] = [new if p == old else p for p in hist["index"]]
        changed = True
    for rec in d.get("tx_log") or []:
        if rec.get("winner") == old:
            rec["winner"] = new
            changed = True
        for t in rec.get("transfers", []):
            if t.get("from") == old:
                t["from"] = new
                changed = True
            if t.get("to") == old:
                t["to"] = new
                changed = True
    return changed


def rename_player(old: str, new: str) -> tuple[bool, str]:
    """Rename a player in the registry AND in all ongoing/finished games."""
    old_clean, new_clean = old.strip(), new.strip()
    if not new_clean:
        return False, "New name is empty."
    with _conn() as c:
        row = c.execute(
            "SELECT player_id, name FROM players WHERE name = ? COLLATE NOCASE", (old_clean,)
        ).fetchone()
        if not row:
            return False, f"No player named '{old_clean}'."
        pid, exact_old = row[0], row[1]
        clash = c.execute(
            "SELECT 1 FROM players WHERE name = ? COLLATE NOCASE AND player_id != ?",
            (new_clean, pid),
        ).fetchone()
        if clash:
            return False, f"A player named '{new_clean}' already exists."

        c.execute("UPDATE players SET name = ? WHERE player_id = ?", (new_clean, pid))

        for r in c.execute("SELECT archive_id, data FROM archived_games").fetchall():
            entry = json.loads(r[1])
            if _rename_in_game_dict(entry, exact_old, new_clean):
                c.execute(
                    "UPDATE archived_games SET data = ? WHERE archive_id = ?",
                    (json.dumps(entry), r[0]),
                )
        for r in c.execute("SELECT game_id, data FROM active_games").fetchall():
            snap = json.loads(r[1])
            tracker = snap.get("tracker")
            if tracker and _rename_in_game_dict(tracker, exact_old, new_clean):
                c.execute(
                    "UPDATE active_games SET data = ? WHERE game_id = ?",
                    (json.dumps(snap), r[0]),
                )
    return True, ""


# ============== Settings (e.g. last-used rules) ==============


def settings_get(key: str, default=None):
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default


def settings_set(key: str, value):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )


# ============== Rulesets (named rule presets) ==============


def ruleset_save(name: str, rules_dict: dict):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO rulesets (name, data) VALUES (?, ?)",
            (name.strip(), json.dumps(rules_dict)),
        )


def rulesets_all() -> dict[str, dict]:
    with _conn() as c:
        rows = c.execute("SELECT name, data FROM rulesets ORDER BY name COLLATE NOCASE").fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}


def ruleset_delete(name: str):
    with _conn() as c:
        c.execute("DELETE FROM rulesets WHERE name = ?", (name,))


# ============== Backup: export / import everything ==============

EXPORT_VERSION = 1


def export_all() -> dict:
    """Full backup of every table as one JSON-serialisable dict."""
    with _conn() as c:
        players = c.execute("SELECT player_id, name, created_at FROM players").fetchall()
        archived = c.execute("SELECT archive_id, created_at, data FROM archived_games").fetchall()
        active = c.execute("SELECT game_id, updated_at, data FROM active_games").fetchall()
        settings = c.execute("SELECT key, value FROM settings").fetchall()
        rulesets = c.execute("SELECT name, data FROM rulesets").fetchall()
    return {
        "version": EXPORT_VERSION,
        "exported_at": _now(),
        "players": [{"player_id": r[0], "name": r[1], "created_at": r[2]} for r in players],
        "archived_games": [json.loads(r[2]) for r in archived],
        "active_games": [
            {"game_id": r[0], "updated_at": r[1], "data": json.loads(r[2])} for r in active
        ],
        "settings": {r[0]: json.loads(r[1]) for r in settings},
        "rulesets": {r[0]: json.loads(r[1]) for r in rulesets},
    }


def import_all(backup: dict):
    """Replace ALL data with the contents of a backup produced by export_all()."""
    if backup.get("version") != EXPORT_VERSION:
        raise ValueError(f"Unsupported backup version: {backup.get('version')!r}")
    with _conn() as c:
        for table in ("players", "archived_games", "active_games", "settings", "rulesets"):
            c.execute(f"DELETE FROM {table}")
        for p in backup.get("players", []):
            c.execute(
                "INSERT INTO players (player_id, name, created_at) VALUES (?, ?, ?)",
                (p["player_id"], p["name"], p.get("created_at") or _now()),
            )
        for entry in backup.get("archived_games", []):
            c.execute(
                "INSERT INTO archived_games (archive_id, created_at, data) VALUES (?, ?, ?)",
                (entry["archive_id"], entry.get("created_at", _now()), json.dumps(entry)),
            )
        for g in backup.get("active_games", []):
            c.execute(
                "INSERT INTO active_games (game_id, updated_at, data) VALUES (?, ?, ?)",
                (g["game_id"], g.get("updated_at") or _now(), json.dumps(g["data"])),
            )
        for key, value in backup.get("settings", {}).items():
            c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        for name, data in backup.get("rulesets", {}).items():
            c.execute("INSERT INTO rulesets (name, data) VALUES (?, ?)", (name, json.dumps(data)))


# ============== Factory reset ==============


def factory_reset():
    with _conn() as c:
        c.execute("DELETE FROM players")
        c.execute("DELETE FROM archived_games")
        c.execute("DELETE FROM active_games")
        c.execute("DELETE FROM settings")
        c.execute("DELETE FROM rulesets")
