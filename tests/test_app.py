"""End-to-end flows through Streamlit's AppTest harness."""

import pytest
from streamlit.testing.v1 import AppTest

import db
from game import CardGameTracker, GameRules


def fresh(app_path, **query):
    at = AppTest.from_file(app_path, default_timeout=20)
    for k, v in query.items():
        at.query_params[k] = v
    return at


def _submit(at):
    [b for b in at.button if getattr(b, "label", "") == "Submit round"][0].click().run()


def _seed_players():
    for n in ("Alice", "Bob", "Charlie"):
        db.player_add(n)


def _seed_finished_game():
    t = CardGameTracker(["Alice", "Bob", "Charlie"], GameRules())
    t.play_round([0, 5, 12])
    t.play_round([3, 0, 8])
    db.archive_add(
        {
            "archive_id": "a1",
            "created_at": "2026-08-01 20:00:00",
            "players": t.players,
            "rounds_played": 2,
            "rules": t.rules.to_dict(),
            "final_totals": {p: float(v) for p, v in t.balances.items()},
            "history": t.history.to_dict(orient="split"),
            "tx_log": t.tx_log,
        }
    )


def test_home_renders_menu(app_path):
    at = fresh(app_path)
    at.run()
    assert not at.exception
    assert {"tile_new", "tile_continue", "tile_analytics", "tile_settings"} <= {
        b.key for b in at.button
    }


def test_full_game_flow(app_path):
    _seed_players()
    at = fresh(app_path)
    at.run()
    at.button(key="tile_new").click().run()
    at.pills(key="ng_player_pills").set_value(["Alice", "Bob", "Charlie"]).run()
    at.button(key="ng_start").click().run()
    assert not at.exception
    assert at.session_state["page"] == "play"
    gid = at.session_state["game_id"]
    g8 = gid[:8]
    assert len(db.games_all()) == 1

    at.number_input(key=f"cards_{g8}_Alice_1").set_value(0)
    at.number_input(key=f"cards_{g8}_Bob_1").set_value(5)
    at.number_input(key=f"cards_{g8}_Charlie_1").set_value(12)
    _submit(at)
    assert not at.exception
    assert at.session_state["round_num"] == 2
    assert abs(sum(at.session_state["tracker"].balances.values())) < 1e-9
    tables = [m.value for m in at.markdown if m.value.startswith('<div class="nice-table-wrap"')]
    assert tables and "win-cell" in tables[0] and "total-row" in tables[0]
    at.segmented_control(key="earn_view").set_value("Trend").run()
    assert not at.exception

    # leave and continue
    at.button(key="back_btn").click().run()
    at.button(key="tile_continue").click().run()
    at.button(key=f"cont_{gid}").click().run()
    assert at.session_state["tracker"].rounds_played == 1

    # refresh restores from URL
    at2 = fresh(app_path, page="play", game_id=gid)
    at2.run()
    assert not at2.exception and at2.session_state["tracker"].rounds_played == 1

    # undo, then finish
    at.number_input(key=f"cards_{g8}_Alice_2").set_value(3)
    at.number_input(key=f"cards_{g8}_Bob_2").set_value(0)
    at.number_input(key=f"cards_{g8}_Charlie_2").set_value(1)
    _submit(at)
    at.button(key="undo_btn").click().run()
    assert at.session_state["round_num"] == 2
    at.button(key="finish_confirm").click().run()
    assert not at.exception
    assert at.session_state["game_finished"] is True
    assert len(db.archive_all()) == 1 and db.games_all() == []
    assert db.settings_get("default_rules") is not None


def test_invalid_round_inputs_are_rejected(app_path):
    _seed_players()
    at = fresh(app_path)
    at.run()
    at.button(key="tile_new").click().run()
    at.pills(key="ng_player_pills").set_value(["Alice", "Bob"]).run()
    at.button(key="ng_start").click().run()
    g8 = at.session_state["game_id"][:8]
    at.number_input(key=f"cards_{g8}_Alice_1").set_value(4)
    at.number_input(key=f"cards_{g8}_Bob_1").set_value(5)
    _submit(at)
    assert at.error and at.session_state["round_num"] == 1


def test_rulesets_save_apply_edit_delete(app_path):
    _seed_players()
    at = fresh(app_path, page="new_game")
    at.run()
    at.number_input(key="ng_cv").set_value(0.5)
    at.text_input(key="ng_rs_name").input("High stakes").run()
    at.button(key="ng_rs_save").click().run()
    assert db.rulesets_all()["High stakes"]["card_value"] == 0.5

    db.ruleset_save("Cheap", {"card_value": 0.1, "base_cards": 1})
    at2 = fresh(app_path, page="new_game")
    at2.run()
    at2.selectbox(key="ng_ruleset").set_value("Cheap").run()
    assert at2.session_state["ng_cv"] == 0.1 and at2.session_state["ng_base"] == 1

    at3 = fresh(app_path, page="settings")
    at3.run()
    at3.text_input(key="rs_new_name").input("Casual").run()
    at3.button(key="rs_new_btn").click().run()
    at3.number_input(key="rs_Casual_cv").set_value(1.0)
    at3.button(key="rs_save_Casual").click().run()
    assert db.rulesets_all()["Casual"]["card_value"] == 1.0
    at3.button(key="rs_del_Casual").click().run()
    assert "Casual" not in db.rulesets_all()


def test_settings_rename_edit_delete(app_path, monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "1234")
    _seed_players()
    _seed_finished_game()
    at = fresh(app_path, page="settings")
    at.session_state["authed"] = True
    at.run()
    at.selectbox(key="pm_rename_old").set_value("Alice")
    at.text_input(key="pm_rename_new").input("Alicia").run()
    at.button(key="pm_rename_btn").click().run()
    assert "Alicia" in db.player_names()
    assert "Alicia" in db.archive_all()[0]["final_totals"]

    at.run()
    at.number_input(key="tot_a1_Alicia").set_value(99.0)
    at.button(key="savetot_a1").click().run()
    assert db.archive_all()[0]["final_totals"]["Alicia"] == 99.0
    at.button(key="del_a1").click().run()
    assert db.archive_all() == []


def test_analytics_renders_with_data(app_path):
    _seed_players()
    _seed_finished_game()
    at = fresh(app_path, page="analytics")
    at.run()
    assert not at.exception
    mds = [m.value for m in at.markdown]
    assert any("stat-card" in v for v in mds)
    assert any("rank-badge gold" in v for v in mds)
    assert at.selectbox(key="an_player").value in ("Alice", "Bob", "Charlie")


@pytest.mark.parametrize("page", ["continue", "analytics", "settings", "new_game"])
def test_pages_render_empty(app_path, page):
    at = fresh(app_path, page=page)
    at.run()
    assert not at.exception


def test_passcode_gate(app_path, monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "1234")
    at = fresh(app_path)
    at.run()
    assert not at.exception
    assert not [b for b in at.button if b.key == "tile_new"], "menu visible without passcode"
    # Typed and submitted in one run: since Streamlit 1.65 an unsubmitted
    # form value is dropped if the script reruns before the submit.
    at.text_input(key="passcode_input").input("wrong")
    [b for b in at.button if getattr(b, "label", "") == "Enter"][0].click().run()
    assert at.error
    at.text_input(key="passcode_input").input("1234")
    [b for b in at.button if getattr(b, "label", "") == "Enter"][0].click().run()
    assert at.session_state["authed"] is True
    assert [b for b in at.button if b.key == "tile_new"]


def test_admin_actions_hidden_without_passcode(app_path):
    _seed_players()
    _seed_finished_game()
    at = fresh(app_path, page="settings")
    at.run()
    assert not at.exception
    keys = {b.key for b in at.button}
    assert "savetot_a1" in keys
    for k in ("del_a1", "backup_restore", "dz_clear_arch", "dz_clear_players", "dz_factory"):
        assert k not in keys, k


def test_admin_actions_shown_behind_passcode(app_path, monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "1234")
    _seed_players()
    _seed_finished_game()
    at = fresh(app_path, page="settings")
    at.session_state["authed"] = True
    at.run()
    keys = {b.key for b in at.button}
    for k in ("del_a1", "backup_restore", "dz_clear_arch", "dz_clear_players", "dz_factory"):
        assert k in keys, k


def test_passcode_gate_throttles_after_repeated_failures(app_path, monkeypatch):
    monkeypatch.setenv("APP_PASSCODE", "1234")
    at = fresh(app_path)
    at.run()

    def attempt(code):
        at.text_input(key="passcode_input").input(code)
        [b for b in at.button if getattr(b, "label", "") == "Enter"][0].click().run()

    for _ in range(5):
        attempt("wrong")
    assert at.session_state["passcode_locked_until"] > 0
    attempt("1234")  # correct, but locked out
    assert "authed" not in at.session_state
    assert any("Too many attempts" in e.value for e in at.error)
