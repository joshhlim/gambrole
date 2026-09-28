"""Taidi Tracker — entry point.

Run with: streamlit run taidi.py

Structure:
    game.py  - game rules (all configurable) + scoring engine + lifetime stats
    db.py    - SQLite persistence (taidi.db): players, games, settings
    ui.py    - all rendering: CSS, home screen, and pages

Navigation: home screen with four tiles (New Game, Continue Game, Analytics,
Settings). The current page and active game are mirrored into the URL query
params so a browser refresh restores where you were.
"""

import streamlit as st

import db
import ui

st.set_page_config(
    page_title="Taidi Tracker",
    page_icon="🀄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

db.init_db()
ui.inject_css()

# Optional shared passcode (set APP_PASSCODE in secrets to enable). Without
# it, the destructive admin actions in Settings are hidden (ui.admin_enabled).
_passcode = db.secret("APP_PASSCODE")
if _passcode and not st.session_state.get("authed"):
    ui.render_passcode(str(_passcode))
    st.stop()

if "page" not in st.session_state:
    st.session_state.page = st.query_params.get("page", "home")

# Restore an in-progress game from ?game_id=... (survives refresh & restarts)
game_id = st.query_params.get("game_id")
if game_id and "tracker" not in st.session_state:
    snap = db.game_load(game_id)
    if snap:
        ui.load_game_into_session(game_id, snap)

if st.session_state.page == "play" and "tracker" not in st.session_state:
    st.session_state.page = "home"

PAGES = {
    "home": ui.render_home,
    "new_game": ui.render_new_game,
    "play": ui.render_play,
    "continue": ui.render_continue,
    "analytics": ui.render_analytics,
    "settings": ui.render_settings,
}
PAGES.get(st.session_state.page, ui.render_home)()
