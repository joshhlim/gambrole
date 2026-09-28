"""All rendering for Taidi Tracker: CSS, navigation, and pages.

Navigation model: a menu-style home screen. Each page has a round back
button in the top-left. The current page (and active game) is mirrored into
the URL query params so a refresh lands you back where you were.
"""

import hmac
import json
import time
from datetime import datetime
from html import escape as _esc
from uuid import uuid4

import pandas as pd
import streamlit as st

import db
from game import CardGameTracker, GameRules, player_history_df, player_stats_df

# ============== Styling ==============

_CSS = """
<style>
/* ---- chrome: hide Streamlit's fixed top bar entirely ---- */
header[data-testid="stHeader"] {display: none;}
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1100px;}

/* ---- home hero / logo ---- */
.home-hero {text-align: center; padding: 30px 0 14px;}
.home-hero svg {display: block; margin: 0 auto 12px;}
.home-hero .title {font-size: 2.1rem; font-weight: 800; letter-spacing: 0.45em;
  margin-left: 0.45em; color: #1E3A2F;}
.home-hero .tag {font-size: 0.78rem; font-weight: 600; letter-spacing: 0.6em;
  margin-left: 0.6em; color: #B3A16A; margin-top: 2px;}

/* ---- home menu buttons: single column, wide & short ---- */
div[class*="st-key-tile_"] {margin-bottom: 10px;}
div[class*="st-key-tile_"] button {
  height: 60px; border-radius: 14px; border: 1px solid #E3DFD4; background: #ffffff;
  box-shadow: 0 2px 8px rgba(30, 40, 30, 0.05); transition: all 0.15s ease;
}
div[class*="st-key-tile_"] button:hover {
  border-color: #1E6B4F; box-shadow: 0 5px 14px rgba(30, 64, 47, 0.14); transform: translateY(-1px);
}
div[class*="st-key-tile_"] button p {font-size: 1.02rem; font-weight: 700; color: #243328;
  letter-spacing: 0.02em;}

/* ---- back button ---- */
.st-key-back_btn button {
  border-radius: 999px; width: 44px; height: 44px; padding: 0;
  font-size: 1.15rem; font-weight: 700; border: 1px solid #E3DFD4; background: #ffffff;
}
.st-key-back_btn button:hover {border-color: #1E6B4F; color: #1E6B4F;}
.page-title {font-size: 1.55rem; font-weight: 800; letter-spacing: -0.01em; color: #1E3A2F;}

/* ---- tabs: segmented control ---- */
.stTabs [data-baseweb="tab-list"] {background: #ECE8DD; padding: 4px; border-radius: 12px;
  gap: 4px; width: fit-content; border-bottom: none;}
.stTabs [data-baseweb="tab"] {background: transparent; border-radius: 9px; padding: 4px 20px;
  height: auto;}
.stTabs [data-baseweb="tab"] p {font-weight: 600; color: #5A5648 !important; font-size: 0.95rem;}
.stTabs [aria-selected="true"] {background: #ffffff; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);}
.stTabs [aria-selected="true"] p {color: #1E3A2F !important;}
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {display: none;}

/* ---- player pills ---- */
[data-testid="stPills"] button {border-radius: 999px; border: 1px solid #D9D4C7;
  background: #ffffff; padding: 4px 18px;}
[data-testid="stPills"] button:hover {border-color: #1E6B4F;}
[data-testid="stPills"] button p {font-weight: 600;}
[data-testid="stBaseButton-pillsActive"] {background: #1E3A2F !important;
  border-color: #1E3A2F !important;}
[data-testid="stBaseButton-pillsActive"] p {color: #ffffff !important;}
[data-testid="stBaseButton-pillsActive"]:hover {background: #1E6B4F !important;}

/* ---- player standings cards ---- */
.player-card {background: #ffffff; border: 1px solid #E3DFD4; border-radius: 16px;
  padding: 16px 12px; text-align: center; box-shadow: 0 2px 10px rgba(30,40,30,0.06);
  margin-bottom: 14px;}
.player-card.leader {background: linear-gradient(135deg, #FFF8E1, #FFE9A8); border-color: #E4C65B;}
.player-card .rank {font-size: 0.85rem; line-height: 1; color: #8A8577; font-weight: 700;
  letter-spacing: 0.08em;}
.player-card .pname {font-size: 1.05rem; font-weight: 700; color: #243328; margin: 6px 0 2px;}
.player-card .pamount {font-size: 1.8rem; font-weight: 800;}
.pos {color: #1E6B4F;} .neg {color: #C0392B;}

/* ---- stat cards (equal height) ---- */
.stat-card {background: #ffffff; border: 1px solid #E3DFD4; border-radius: 14px; height: 112px;
  padding: 12px 16px; box-shadow: 0 2px 8px rgba(30,40,30,0.05); display: flex;
  flex-direction: column; justify-content: center; gap: 2px; margin-bottom: 12px;}
.stat-card .stat-label {font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: #8A8577; font-weight: 600;}
.stat-card .stat-value {font-size: 1.5rem; font-weight: 800; color: #1E3A2F; line-height: 1.15;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.stat-card .stat-sub {font-size: 0.95rem; font-weight: 700;}

/* ---- custom tables ---- */
.nice-table-wrap {background: #ffffff; border: 1px solid #E3DFD4; border-radius: 14px;
  padding: 4px 14px; box-shadow: 0 2px 8px rgba(30,40,30,0.05); overflow-x: auto;
  margin-bottom: 12px;}
table.nice {width: 100%; border-collapse: collapse; font-size: 0.92rem;}
table.nice th {text-align: left; padding: 10px; color: #8A8577; font-size: 0.72rem;
  text-transform: uppercase; letter-spacing: 0.08em; border-bottom: 1px solid #E3DFD4;
  white-space: nowrap;}
table.nice td {padding: 9px 10px; border-bottom: 1px solid #F0EDE4; color: #243328;
  white-space: nowrap;}
table.nice tbody tr:last-child td {border-bottom: none;}
table.nice th.r, table.nice td.r {text-align: right;}
.amt-pos {color: #1E6B4F; font-weight: 600;}
.amt-neg {color: #C0392B; font-weight: 600;}
td.muted, .muted {color: #B0AA99; font-weight: 400;}
table.nice tr.total-row td {border-top: 2px solid #E3DFD4; font-weight: 700; background: #FBF9F2;}
td.win-cell {background: #FFF8E1; border-radius: 6px;}
.rank-badge {display: inline-block; min-width: 26px; text-align: center; border-radius: 999px;
  padding: 1px 8px; font-weight: 700; font-size: 0.8rem; background: #ECE8DD; color: #5A5648;}
.rank-badge.gold {background: #F3D97E; color: #5B4A12;}
.rank-badge.silver {background: #E4E2DC; color: #55534C;}
.rank-badge.bronze {background: #E8CFB2; color: #6B4A26;}

/* ---- forms & buttons ---- */
[data-testid="stForm"] {background: #ffffff; border: 1px solid #E3DFD4; border-radius: 16px;
  padding: 18px; box-shadow: 0 2px 10px rgba(30,40,30,0.05);}
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 10px; font-weight: 600;}
</style>
"""

_LOGO_SVG = """
<svg width="170" height="118" viewBox="0 0 170 118" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Taidi Tracker logo">
  <g transform="rotate(-16 58 72)">
    <rect x="30" y="26" width="56" height="78" rx="9" fill="#EFEBDF" stroke="#D6D0BF" stroke-width="1.5"/>
  </g>
  <g transform="rotate(16 112 72)">
    <rect x="84" y="26" width="56" height="78" rx="9" fill="#EFEBDF" stroke="#D6D0BF" stroke-width="1.5"/>
  </g>
  <rect x="57" y="14" width="56" height="82" rx="9" fill="#1E3A2F" stroke="#14291F" stroke-width="1.5"/>
  <text x="67" y="38" font-family="Georgia, 'Times New Roman', serif" font-size="17" font-weight="bold" fill="#D9B44A">2</text>
  <text x="71" y="53" text-anchor="middle" font-size="13" fill="#D9B44A">&#9824;</text>
  <text x="85" y="78" text-anchor="middle" font-size="34" fill="#D9B44A">&#9824;</text>
</svg>
"""


def inject_css():
    st.markdown(_CSS, unsafe_allow_html=True)


def money(v) -> str:
    v = float(v)
    return f"-${abs(v):,.2f}" if v < -1e-9 else f"${v:,.2f}"


def _neg_red(v):
    try:
        return "color: #C0392B; font-weight: 600" if float(v) < 0 else ""
    except (TypeError, ValueError):
        return ""


# ============== Custom components ==============

_CHART_COLORS = [
    "#1E6B4F",
    "#D9B44A",
    "#B3592E",
    "#3B6EA5",
    "#8A5CA5",
    "#C0392B",
    "#5A5648",
    "#2AA198",
]


def _stat_cards(cards: list[tuple[str, str, str]]):
    """Row of equal-height stat cards. Each card: (label, value_html, sub_html)."""
    cols = st.columns(len(cards))
    for col, (label, value, sub) in zip(cols, cards, strict=True):
        sub_html = f'<div class="stat-sub">{sub}</div>' if sub else ""
        col.markdown(
            f'<div class="stat-card"><div class="stat-label">{label}</div>'
            f'<div class="stat-value">{value}</div>{sub_html}</div>',
            unsafe_allow_html=True,
        )


def _cell(text, cls: str = "") -> str:
    return f'<td class="{cls}">{text}</td>'


def _nice_table(headers: list[tuple[str, str]], rows: list[tuple[str, list[str]]]) -> str:
    """Single-line HTML table. headers: (label, cls); rows: (row_cls, [cell_html])."""
    th = "".join(f'<th class="{c}">{h}</th>' for h, c in headers)
    trs = "".join(f'<tr class="{rc}">{"".join(cells)}</tr>' for rc, cells in rows)
    return (
        '<div class="nice-table-wrap"><table class="nice">'
        f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>"
    )


def _amt_cls(v: float) -> str:
    return "amt-neg" if v < 0 else "amt-pos"


def _fmt_delta(d: float) -> tuple[str, str]:
    if abs(d) < 1e-9:
        return "—", "muted"
    if d > 0:
        return f"+{money(d)}", "amt-pos"
    return money(d), "amt-neg"


def _round_earnings_html(
    history_df: pd.DataFrame, players: list[str], totals: dict, winners: list
) -> str:
    headers = [("Round", "")] + [(_esc(p), "r") for p in players]
    rows = []
    prev = {p: 0.0 for p in players}
    for i, col in enumerate(history_df.columns):
        winner = winners[i] if i < len(winners) else None
        cells = [_cell(str(i + 1), "muted")]
        for p in players:
            cur = float(history_df.loc[p, col])
            txt, cls = _fmt_delta(cur - prev[p])
            prev[p] = cur
            if p == winner:
                cls += " win-cell"
            cells.append(_cell(txt, f"r {cls}"))
        rows.append(("", cells))
    total_cells = [_cell("Total")]
    for p in players:
        v = float(totals.get(p, 0.0))
        total_cells.append(_cell(money(v), f"r {_amt_cls(v)}"))
    rows.append(("total-row", total_cells))
    return _nice_table(headers, rows)


def _render_round_earnings(
    history_df: pd.DataFrame, players: list[str], totals: dict, winners: list, key: str
):
    view = st.segmented_control(
        "View",
        ["By round", "Trend"],
        default="By round",
        key=key,
        label_visibility="collapsed",
    )
    if view == "Trend":
        cum = history_df.T.copy()
        cum = cum[[p for p in players if p in cum.columns]]
        cum.index = range(1, len(cum) + 1)
        zero = pd.DataFrame([{p: 0.0 for p in cum.columns}], index=[0])
        st.line_chart(pd.concat([zero, cum]), color=_CHART_COLORS[: len(cum.columns)])
    else:
        st.markdown(
            _round_earnings_html(history_df, players, totals, winners),
            unsafe_allow_html=True,
        )


def _render_leaderboard(stats: pd.DataFrame):
    headers = [
        ("", ""),
        ("Player", ""),
        ("Games", "r"),
        ("Total", "r"),
        ("Avg / game", "r"),
        ("W – L – T", "r"),
        ("Last played", "r"),
    ]
    rows = []
    badge_tiers = {0: "gold", 1: "silver", 2: "bronze"}
    for i, row in stats.reset_index(drop=True).iterrows():
        badge = badge_tiers.get(i, "")
        total = float(row["Total"])
        avg = float(row["Avg/Game"])
        rows.append(
            (
                "",
                [
                    _cell(f'<span class="rank-badge {badge}">{i + 1}</span>'),
                    _cell(f"<b>{_esc(str(row['Player']))}</b>"),
                    _cell(str(int(row["Games"])), "r"),
                    _cell(money(total), f"r {_amt_cls(total)}"),
                    _cell(money(avg), f"r {_amt_cls(avg)}"),
                    _cell(f"{int(row['W'])} – {int(row['L'])} – {int(row['T'])}", "r"),
                    _cell(_esc(str(row["Last Played"])), "r muted"),
                ],
            )
        )
    st.markdown(_nice_table(headers, rows), unsafe_allow_html=True)


def _pergame_html(trend: pd.DataFrame) -> str:
    headers = [
        ("When", ""),
        ("Rounds", "r"),
        ("Card value", "r"),
        ("Net", "r"),
        ("Cumulative", "r"),
    ]
    rows = []
    for _, r in trend.iloc[::-1].iterrows():
        net = float(r["Net"])
        cum = float(r["Cumulative"])
        rows.append(
            (
                "",
                [
                    _cell(r["When"].strftime("%Y-%m-%d %H:%M")),
                    _cell(str(int(r["Rounds"])), "r"),
                    _cell(money(r["Card Value"]), "r muted"),
                    _cell(money(net), f"r {_amt_cls(net)}"),
                    _cell(money(cum), f"r {_amt_cls(cum)}"),
                ],
            )
        )
    return _nice_table(headers, rows)


# ============== Navigation ==============


def goto(page: str, game_id: str | None = None):
    st.session_state.page = page
    params = {"page": page}
    if game_id:
        params["game_id"] = game_id
    st.query_params.from_dict(params)
    st.rerun()


def _top_bar(title: str):
    col_back, col_title = st.columns([1, 11], vertical_alignment="center")
    if col_back.button("←", key="back_btn"):
        goto("home")
    col_title.markdown(f'<div class="page-title">{title}</div>', unsafe_allow_html=True)
    st.markdown("")


# ============== Game session helpers ==============


def load_game_into_session(game_id: str, snap: dict):
    st.session_state.tracker = CardGameTracker.from_snapshot(snap["tracker"])
    st.session_state.round_num = snap.get("round_num", st.session_state.tracker.rounds_played + 1)
    st.session_state.game_id = game_id
    st.session_state.game_finished = False
    st.session_state.undo_stack = []


def _clear_game_session():
    for k in ("tracker", "round_num", "game_id", "game_finished", "undo_stack"):
        st.session_state.pop(k, None)


def _save_active_game():
    if (
        "game_id" in st.session_state
        and "tracker" in st.session_state
        and not st.session_state.get("game_finished")
    ):
        db.game_save(
            st.session_state.game_id,
            {
                "tracker": st.session_state.tracker.to_snapshot(),
                "round_num": st.session_state.round_num,
            },
        )


def _sync_session_if_current(game_id: str):
    if st.session_state.get("game_id") == game_id:
        snap = db.game_load(game_id)
        if snap:
            load_game_into_session(game_id, snap)


# ============== Rules editor (shared) ==============

_RULE_WIDGETS = {
    "cv": ("card_value", float),
    "base": ("base_cards", int),
    "mult": ("multipliers_enabled", bool),
    "dbl": ("double_threshold", int),
    "trp": ("triple_threshold", int),
    "diff": ("difference_payouts", bool),
    "spec": ("special_hands_enabled", bool),
    "specn": ("special_hand_cards", int),
}


def apply_rules_to_widgets(prefix: str, rules: GameRules):
    for short, (attr, cast) in _RULE_WIDGETS.items():
        st.session_state[f"{prefix}_{short}"] = cast(getattr(rules, attr))


def _seed_rules_widgets(prefix: str, initial: GameRules):
    for short, (attr, cast) in _RULE_WIDGETS.items():
        key = f"{prefix}_{short}"
        if key not in st.session_state:
            st.session_state[key] = cast(getattr(initial, attr))


def rules_editor(prefix: str, initial: GameRules) -> GameRules:
    """Render the rules form. Unique `prefix` keeps widget keys distinct."""
    _seed_rules_widgets(prefix, initial)

    def k(name):
        return f"{prefix}_{name}"

    r1c1, r1c2 = st.columns(2)
    card_value = r1c1.number_input(
        "Value per card ($)", min_value=0.0, step=0.05, format="%.2f", key=k("cv")
    )
    base_cards = int(
        r1c2.number_input("Base cards to winner", min_value=0, max_value=20, step=1, key=k("base"))
    )

    multipliers_enabled = st.toggle("Double / triple penalties", key=k("mult"))
    mcol1, mcol2 = st.columns(2)
    double_threshold = int(
        mcol1.number_input(
            "×2 at ≥",
            min_value=1,
            max_value=52,
            step=1,
            disabled=not multipliers_enabled,
            key=k("dbl"),
        )
    )
    triple_threshold = int(
        mcol2.number_input(
            "×3 at ≥",
            min_value=1,
            max_value=52,
            step=1,
            disabled=not multipliers_enabled,
            key=k("trp"),
        )
    )
    if multipliers_enabled and triple_threshold < double_threshold:
        st.warning("×3 threshold is below the ×2 threshold.")

    difference_payouts = st.toggle("Difference payouts between losers", key=k("diff"))

    scol1, scol2 = st.columns(2, vertical_alignment="bottom")
    with scol1:
        special_hands_enabled = st.toggle("Special hands", key=k("spec"))
    special_hand_cards = int(
        scol2.number_input(
            "Cards per special hand",
            min_value=1,
            max_value=20,
            step=1,
            disabled=not special_hands_enabled,
            key=k("specn"),
        )
    )

    return GameRules(
        card_value=card_value,
        base_cards=base_cards,
        multipliers_enabled=multipliers_enabled,
        double_threshold=double_threshold,
        triple_threshold=triple_threshold,
        difference_payouts=difference_payouts,
        special_hands_enabled=special_hands_enabled,
        special_hand_cards=special_hand_cards,
    )


# ============== Shared widgets ==============


def _render_standings(balances: dict):
    standings = sorted(balances.items(), key=lambda x: x[1], reverse=True)
    num_cols = min(4, max(1, len(standings)))
    cols = st.columns(num_cols)
    for idx, (name, amt) in enumerate(standings):
        card_cls = "leader" if idx == 0 else ""
        amount_cls = "neg" if amt < 0 else "pos"
        cols[idx % num_cols].markdown(
            f"""
            <div class="player-card {card_cls}">
              <div class="rank">#{idx + 1}</div>
              <div class="pname">{name}</div>
              <div class="pamount {amount_cls}">{money(amt)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


_KIND_LABEL = {
    "cards": "cards left",
    "difference": "difference",
    "base": "base",
    "special": "special hand",
}


def _transfers_df(transfers: list[dict]) -> pd.DataFrame:
    rows = []
    for t in transfers:
        cards = f"{t['cards']} × {t['mult']}" if t.get("mult", 1) > 1 else f"{t['cards']}"
        rows.append(
            {
                "From": t["from"],
                "To": t["to"],
                "Type": _KIND_LABEL.get(t["kind"], t["kind"]),
                "Cards": cards,
                "Amount": t["amount"],
            }
        )
    return pd.DataFrame(rows)


def _game_line(tracker_snap: dict) -> str:
    players = tracker_snap.get("players", [])
    rounds = len(tracker_snap.get("history", {}).get("columns", []))
    return f"**{', '.join(players)}** — {rounds} round{'s' if rounds != 1 else ''} played"


# ============== Passcode gate ==============


_PASSCODE_FREE_TRIES = 5


def render_passcode(expected: str):
    """Shared-PIN gate shown before any page when APP_PASSCODE is configured."""
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown(
            '<div class="home-hero">'
            + _LOGO_SVG.replace("\n", " ")
            + '<div class="title">TAIDI</div><div class="tag">TRACKER</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("passcode_form"):
            entered = st.text_input(
                "Passcode",
                type="password",
                key="passcode_input",
                label_visibility="collapsed",
                placeholder="Passcode",
            )
            if st.form_submit_button("Enter", type="primary", width="stretch"):
                wait = st.session_state.get("passcode_locked_until", 0.0) - time.time()
                if wait > 0:
                    st.error(f"Too many attempts. Try again in {int(wait) + 1}s.")
                elif hmac.compare_digest(entered.encode(), expected.encode()):
                    st.session_state.authed = True
                    st.session_state.pop("passcode_fails", None)
                    st.rerun()
                else:
                    fails = st.session_state.get("passcode_fails", 0) + 1
                    st.session_state.passcode_fails = fails
                    if fails >= _PASSCODE_FREE_TRIES:
                        # 30s, 60s, 120s ... capped at 15 minutes
                        backoff = min(30 * 2 ** (fails - _PASSCODE_FREE_TRIES), 900)
                        st.session_state.passcode_locked_until = time.time() + backoff
                    st.error("Wrong passcode.")


def admin_enabled() -> bool:
    """Restore, delete and reset are only offered behind the passcode gate."""
    return bool(db.secret("APP_PASSCODE"))


# ============== Page: Home ==============


def render_home():
    hero = (
        '<div class="home-hero">'
        + _LOGO_SVG.replace("\n", " ")
        + '<div class="title">TAIDI</div>'
        + '<div class="tag">TRACKER</div>'
        + "</div>"
    )
    st.markdown(hero, unsafe_allow_html=True)
    st.markdown("")

    _, col, _ = st.columns([1, 1.5, 1])
    with col:
        for key, label, page in (
            ("tile_new", "New Game", "new_game"),
            ("tile_continue", "Continue Game", "continue"),
            ("tile_analytics", "Analytics", "analytics"),
            ("tile_settings", "Settings", "settings"),
        ):
            if st.button(label, key=key, width="stretch"):
                goto(page)


# ============== Page: New Game ==============


def _ng_apply_ruleset():
    name = st.session_state.get("ng_ruleset")
    rulesets = db.rulesets_all()
    if name in rulesets:
        apply_rules_to_widgets("ng", GameRules.from_dict(rulesets[name]))


def render_new_game():
    _top_bar("New Game")

    st.markdown("##### Players")
    names = db.player_names()
    if not names:
        st.info("No players yet — add them in Settings.")
        selected = []
    else:
        container = st.container(height=170, border=False) if len(names) > 16 else st.container()
        with container:
            selected = (
                st.pills(
                    "Players",
                    options=names,
                    selection_mode="multi",
                    key="ng_player_pills",
                    label_visibility="collapsed",
                )
                or []
            )

    st.markdown("##### Rules")
    rulesets = db.rulesets_all()
    if rulesets:
        st.selectbox(
            "Ruleset",
            options=["Custom"] + list(rulesets.keys()),
            key="ng_ruleset",
            on_change=_ng_apply_ruleset,
        )
    saved = GameRules.from_dict(db.settings_get("default_rules"))
    rules = rules_editor("ng", saved)

    rcol1, rcol2 = st.columns([3, 1], vertical_alignment="bottom")
    ruleset_name = rcol1.text_input("Save as ruleset", key="ng_rs_name", placeholder="Ruleset name")
    if rcol2.button("Save", key="ng_rs_save", width="stretch"):
        clean = ruleset_name.strip()
        if clean:
            db.ruleset_save(clean, rules.to_dict())
            st.toast(f"Ruleset saved: {clean}")
            st.rerun()
        else:
            st.warning("Enter a ruleset name.")

    st.markdown("---")
    if st.button("Start Game", type="primary", key="ng_start", width="stretch"):
        if len(selected) < 2:
            st.error("Select at least two players.")
        else:
            game_id = str(uuid4())
            st.session_state.tracker = CardGameTracker(selected, rules)
            st.session_state.round_num = 1
            st.session_state.game_id = game_id
            st.session_state.game_finished = False
            st.session_state.undo_stack = []
            db.game_save(
                game_id,
                {
                    "tracker": st.session_state.tracker.to_snapshot(),
                    "round_num": 1,
                },
            )
            db.settings_set("default_rules", rules.to_dict())
            goto("play", game_id)


# ============== Page: Play (the active game) ==============


def render_play():
    if "tracker" not in st.session_state:
        goto("home")
        return

    tracker: CardGameTracker = st.session_state.tracker
    rules = tracker.rules
    finished = st.session_state.get("game_finished", False)
    gid8 = st.session_state.game_id[:8]

    _top_bar("Game Over" if finished else "Game")
    st.caption(f"{', '.join(tracker.players)} · {rules.describe()}")

    if finished:
        st.success("Game finished — results saved to Analytics.")
        _render_standings(tracker.balances)
        if tracker.rounds_played > 0:
            with st.expander("Earnings by round"):
                _render_round_earnings(
                    tracker.history,
                    tracker.players,
                    tracker.balances,
                    [r["winner"] for r in tracker.tx_log],
                    key="earn_view_done",
                )
        if st.button("Back to home", type="primary", key="finished_home"):
            _clear_game_session()
            goto("home")
        return

    round_num = st.session_state.round_num
    st.markdown(f"#### Round {round_num}")

    with st.form(key=f"round_form_{gid8}_{round_num}"):
        st.markdown("**Cards left**")
        cols = st.columns(len(tracker.players))
        card_counts = []
        for i, player in enumerate(tracker.players):
            card_counts.append(
                int(
                    cols[i].number_input(
                        player,
                        min_value=0,
                        max_value=52,
                        step=1,
                        key=f"cards_{gid8}_{player}_{round_num}",
                    )
                )
            )

        special_counts: dict[str, int] = {}
        if rules.special_hands_enabled:
            st.markdown("**Special hands**")
            cols_s = st.columns(len(tracker.players))
            for i, player in enumerate(tracker.players):
                special_counts[player] = int(
                    cols_s[i].number_input(
                        player,
                        min_value=0,
                        max_value=10,
                        step=1,
                        key=f"special_{gid8}_{player}_{round_num}",
                    )
                )

        submitted = st.form_submit_button("Submit round", type="primary", width="stretch")

    if submitted:
        zero_count = sum(1 for c in card_counts if c == 0)
        if zero_count == 0:
            st.error("No winner — exactly one player must have 0 cards.")
        elif zero_count > 1:
            st.error("More than one player has 0 cards — only one winner per round.")
        else:
            try:
                undo_stack = st.session_state.get("undo_stack") or []
                st.session_state.undo_stack = undo_stack[-19:] + [tracker.to_snapshot()]
                tracker.play_round(
                    card_counts,
                    round_name=f"Round {round_num}",
                    special_hand_counts=special_counts,
                )
                st.session_state.round_num += 1
                _save_active_game()
                st.rerun()
            except ValueError as e:
                st.error(f"Error: {e}")

    if tracker.tx_log:
        last = tracker.tx_log[-1]
        bcol1, bcol2 = st.columns([4, 1], vertical_alignment="center")
        with bcol1:
            with st.expander(f"{last['round']}: **{last['winner']}** won — payout breakdown"):
                st.dataframe(
                    _transfers_df(last["transfers"]).style.format({"Amount": money}),
                    width="stretch",
                    hide_index=True,
                )
        if st.session_state.get("undo_stack"):
            if bcol2.button("Undo round", key="undo_btn", width="stretch"):
                snap = st.session_state.undo_stack.pop()
                st.session_state.tracker = CardGameTracker.from_snapshot(snap)
                st.session_state.round_num -= 1
                _save_active_game()
                st.rerun()

    st.markdown("#### Standings")
    _render_standings(tracker.balances)

    if tracker.rounds_played > 0:
        st.markdown("#### Earnings by round")
        _render_round_earnings(
            tracker.history,
            tracker.players,
            tracker.balances,
            [r["winner"] for r in tracker.tx_log],
            key="earn_view",
        )

        st.markdown("---")
        with st.popover("Finish game"):
            st.markdown("Save the results to Analytics? The game can't be continued afterwards.")
            if st.button("Finish & save", type="primary", key="finish_confirm"):
                _finish_game()


def _finish_game():
    tracker: CardGameTracker = st.session_state.tracker
    entry = {
        "archive_id": str(uuid4()),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "game_id": st.session_state.get("game_id"),
        "players": tracker.players,
        "rounds_played": tracker.rounds_played,
        "rules": tracker.rules.to_dict(),
        "final_totals": {p: float(v) for p, v in tracker.balances.items()},
        "history": tracker.history.to_dict(orient="split"),
        "tx_log": tracker.tx_log,
    }
    db.archive_add(entry)
    db.game_delete(st.session_state.game_id)
    st.session_state.game_finished = True
    st.rerun()


# ============== Page: Continue Game ==============


def render_continue():
    _top_bar("Continue Game")

    games = db.games_all()
    if not games:
        st.info("No unfinished games.")
        return

    for g in games:
        tracker_snap = g["data"].get("tracker", {})
        rules = GameRules.from_dict(tracker_snap.get("rules"))
        with st.container(border=True):
            icol, bcol = st.columns([4, 1], vertical_alignment="center")
            with icol:
                st.markdown(_game_line(tracker_snap))
                st.caption(f"Last played {g['updated_at']} · {rules.describe()}")
            if bcol.button("Continue", key=f"cont_{g['game_id']}", width="stretch"):
                load_game_into_session(g["game_id"], g["data"])
                goto("play", g["game_id"])


# ============== Page: Analytics ==============


def render_analytics():
    _top_bar("Analytics")

    archive = db.archive_all()
    if not archive:
        st.info("No finished games yet.")
        return

    stats = player_stats_df(archive)
    total_rounds = sum(e.get("rounds_played", 0) for e in archive)
    top = stats.iloc[0]
    bottom = stats.iloc[-1]

    _stat_cards(
        [
            ("Games recorded", str(len(archive)), ""),
            ("Rounds played", str(total_rounds), ""),
            (
                "Top earner",
                _esc(str(top["Player"])),
                f'<span class="amt-pos">{money(top["Total"])}</span>',
            ),
            (
                "Deepest pockets",
                _esc(str(bottom["Player"])),
                f'<span class="{_amt_cls(float(bottom["Total"]))}">{money(bottom["Total"])}</span>',
            ),
        ]
    )

    st.markdown("##### Leaderboard")
    _render_leaderboard(stats)

    st.markdown("##### Player deep dive")
    names = sorted(stats["Player"].tolist(), key=str.lower)
    sel = st.selectbox("Player", options=names, key="an_player")
    hist = player_history_df(archive, sel)
    games = len(hist)
    total = float(hist["Net"].sum()) if games else 0.0
    wins = int((hist["Net"] > 0).sum())
    winrate = wins / games * 100.0 if games else 0.0
    avg = total / games if games else 0.0

    _stat_cards(
        [
            ("Profit / Loss", f'<span class="{_amt_cls(total)}">{money(total)}</span>', ""),
            ("Win rate", f"{winrate:.0f}%", ""),
            ("Games", str(games), ""),
            ("Avg / game", f'<span class="{_amt_cls(avg)}">{money(avg)}</span>', ""),
        ]
    )

    if games:
        trend = hist.copy()
        trend["When"] = pd.to_datetime(trend["When"], errors="coerce")
        trend = trend.dropna(subset=["When"]).sort_values("When")
        trend["Cumulative"] = trend["Net"].cumsum()
        st.line_chart(trend, x="When", y="Cumulative", color="#1E6B4F")
        with st.expander("Per-game results"):
            st.markdown(_pergame_html(trend), unsafe_allow_html=True)


# ============== Page: Settings ==============


def render_settings():
    _top_bar("Settings")
    tab_players, tab_games, tab_rulesets = st.tabs(["Players", "Games", "Rulesets"])
    with tab_players:
        _render_settings_players()
    with tab_games:
        _render_settings_games()
    with tab_rulesets:
        _render_settings_rulesets()


def _render_settings_players():
    st.markdown("##### Add players")
    acol1, acol2 = st.columns([3, 1], vertical_alignment="bottom")
    new_names = acol1.text_input("Names", key="pm_add", placeholder="Alice, Bob, Charlie")
    if acol2.button("Add", key="pm_add_btn", width="stretch"):
        names = [n.strip() for n in new_names.split(",") if n.strip()]
        if names:
            for n in names:
                db.player_add(n)
            st.toast(f"Added: {', '.join(names)}")
            st.rerun()
        else:
            st.warning("Enter at least one name.")

    reg_names = db.player_names()

    st.markdown("##### Rename a player")
    if not reg_names:
        st.caption("No players yet.")
    else:
        rcol1, rcol2, rcol3 = st.columns([2, 2, 1], vertical_alignment="bottom")
        old_name = rcol1.selectbox("Player", options=reg_names, key="pm_rename_old")
        new_name = rcol2.text_input("New name", key="pm_rename_new")
        if rcol3.button("Rename", key="pm_rename_btn", width="stretch"):
            ok, err = db.rename_player(old_name, new_name)
            if ok:
                if "game_id" in st.session_state:
                    _sync_session_if_current(st.session_state.game_id)
                st.toast(f"Renamed {old_name} to {new_name.strip()}")
                st.rerun()
            else:
                st.error(err)

    st.markdown("##### Remove players")
    if not reg_names:
        st.caption("No players to remove.")
    else:
        to_remove = st.multiselect("Players to remove", options=reg_names, key="pm_remove")
        if st.button("Remove selected", key="pm_remove_btn"):
            active = db.names_in_active_games()
            removed, blocked = [], []
            for name in to_remove:
                if name in active:
                    blocked.append(name)
                elif db.player_delete(name):
                    removed.append(name)
                else:
                    blocked.append(name)
            if removed:
                st.success(f"Removed: {', '.join(removed)}")
            if blocked:
                st.warning(f"Could not remove (in an unfinished game): {', '.join(blocked)}")

    st.markdown("##### Registered players")
    reg_names = db.player_names()
    if not reg_names:
        st.caption("No players in the registry.")
    else:
        stats = player_stats_df(db.archive_all()).set_index("Player")
        rows = []
        for name in reg_names:
            if name in stats.index:
                s = stats.loc[name]
                rows.append(
                    {
                        "Player": name,
                        "Games": int(s["Games"]),
                        "Total": float(s["Total"]),
                        "Avg/Game": float(s["Avg/Game"]),
                        "W": int(s["W"]),
                        "L": int(s["L"]),
                        "T": int(s["T"]),
                        "Last Played": s["Last Played"],
                    }
                )
            else:
                rows.append(
                    {
                        "Player": name,
                        "Games": 0,
                        "Total": 0.0,
                        "Avg/Game": 0.0,
                        "W": 0,
                        "L": 0,
                        "T": 0,
                        "Last Played": "-",
                    }
                )
        st.dataframe(
            pd.DataFrame(rows)
            .style.format({"Total": money, "Avg/Game": money})
            .map(_neg_red, subset=["Total", "Avg/Game"]),
            width="stretch",
            hide_index=True,
        )


def _render_settings_games():
    st.markdown("##### Ongoing games")
    games = db.games_all()
    if not games:
        st.caption("No unfinished games.")
    for g in games:
        gid = g["game_id"]
        snap = g["data"]
        tracker_snap = snap.get("tracker", {})
        rules = GameRules.from_dict(tracker_snap.get("rules"))
        title = f"{_game_line(tracker_snap)} · last played {g['updated_at']}"
        with st.expander(title.replace("**", "")):
            st.caption(rules.describe())

            st.markdown("**Balances**")
            balances = tracker_snap.get("balances", {})
            bcols = st.columns(min(4, max(1, len(balances))))
            new_balances = {}
            for i, (name, val) in enumerate(balances.items()):
                new_balances[name] = bcols[i % len(bcols)].number_input(
                    name,
                    value=float(val),
                    step=0.1,
                    format="%.2f",
                    key=f"bal_{gid[:8]}_{name}",
                )
            drift = sum(new_balances.values())
            if abs(drift) > 1e-9:
                st.caption(f"Balances sum to {money(drift)} — a zero-sum game should sum to $0.00.")
            if st.button("Save balances", key=f"savebal_{gid[:8]}"):
                tracker_snap["balances"] = {n: float(v) for n, v in new_balances.items()}
                db.game_save(gid, snap)
                _sync_session_if_current(gid)
                st.toast("Balances updated")
                st.rerun()

            if st.toggle("Edit rules", key=f"editrules_{gid[:8]}"):
                new_rules = rules_editor(f"gr_{gid[:8]}", rules)
                if st.button("Save rules", key=f"saverules_{gid[:8]}"):
                    tracker_snap["rules"] = new_rules.to_dict()
                    db.game_save(gid, snap)
                    _sync_session_if_current(gid)
                    st.toast("Rules updated")
                    st.rerun()

            if st.button("Delete this game", key=f"delgame_{gid[:8]}"):
                db.game_delete(gid)
                if st.session_state.get("game_id") == gid:
                    _clear_game_session()
                st.toast("Game deleted")
                st.rerun()

    st.markdown("---")

    st.markdown("##### Finished games")
    archive = db.archive_all()
    if not archive:
        st.caption("No finished games yet.")
    for entry in archive:
        aid = entry["archive_id"]
        rules = GameRules.from_dict(entry.get("rules"))
        players = entry.get("players", [])
        title = (
            f"{entry.get('created_at', '?')} — {', '.join(players)} · "
            f"{entry.get('rounds_played', 0)} rounds"
        )
        with st.expander(title):
            st.caption(rules.describe())

            st.markdown("**Final totals**")
            totals = entry.get("final_totals", {})
            tcols = st.columns(min(4, max(1, len(totals))))
            new_totals = {}
            for i, (name, val) in enumerate(totals.items()):
                new_totals[name] = tcols[i % len(tcols)].number_input(
                    name,
                    value=float(val),
                    step=0.1,
                    format="%.2f",
                    key=f"tot_{aid[:8]}_{name}",
                )
            drift = sum(new_totals.values())
            if abs(drift) > 1e-9:
                st.caption(f"Totals sum to {money(drift)} — a zero-sum game should sum to $0.00.")
            if st.button("Save totals", key=f"savetot_{aid[:8]}"):
                entry["final_totals"] = {n: float(v) for n, v in new_totals.items()}
                db.archive_add(entry)
                st.toast("Totals updated")
                st.rerun()

            hist = entry.get("history")
            if hist and st.toggle("Round-by-round", key=f"rounds_{aid[:8]}"):
                hdf = pd.DataFrame(data=hist["data"], index=hist["index"], columns=hist["columns"])
                st.markdown(
                    _round_earnings_html(
                        hdf,
                        entry.get("players", list(hdf.index)),
                        entry.get("final_totals", {}),
                        [r.get("winner") for r in entry.get("tx_log", [])],
                    ),
                    unsafe_allow_html=True,
                )

            dcol1, dcol2 = st.columns(2)
            csv_df = pd.Series(totals).sort_values(ascending=False).reset_index()
            csv_df.columns = ["Player", "Total"]
            stamp = entry.get("created_at", "game").replace(" ", "_").replace(":", "-")
            dcol1.download_button(
                "Download CSV",
                data=csv_df.to_csv(index=False),
                file_name=f"taidi_{stamp}.csv",
                mime="text/csv",
                key=f"dl_{aid[:8]}",
            )
            if admin_enabled() and dcol2.button("Delete this game", key=f"del_{aid[:8]}"):
                db.archive_delete(aid)
                st.toast("Game deleted")
                st.rerun()

    st.markdown("---")
    with st.expander("Backup"):
        st.download_button(
            "Download backup (JSON)",
            data=json.dumps(db.export_all(), indent=2),
            file_name=f"taidi_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
            mime="application/json",
            key="backup_download",
            width="stretch",
        )
        if admin_enabled():
            uploaded = st.file_uploader("Restore from backup", type=["json"], key="backup_upload")
            confirm = st.checkbox("Replace ALL current data with this backup", key="backup_confirm")
            if st.button("Restore", key="backup_restore", disabled=not (uploaded and confirm)):
                try:
                    db.import_all(json.load(uploaded))
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    st.error(f"Could not restore: {e}")
                else:
                    for k in list(st.session_state.keys()):
                        if k != "authed":
                            del st.session_state[k]
                    st.toast("Backup restored")
                    st.rerun()

    if not admin_enabled():
        return
    st.markdown("---")
    with st.expander("Danger zone"):
        dcol1, dcol2 = st.columns(2)
        if dcol1.button("Clear all finished games", key="dz_clear_arch", width="stretch"):
            db.archive_clear()
            st.toast("Finished games cleared")
            st.rerun()
        if dcol2.button("Clear player registry", key="dz_clear_players", width="stretch"):
            db.players_clear()
            st.toast("Player registry cleared")
            st.rerun()

        sure = st.checkbox("I understand this deletes ALL data", key="confirm_factory_reset")
        if st.button("Full factory reset", type="primary", key="dz_factory", disabled=not sure):
            db.factory_reset()
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.query_params.clear()
            st.rerun()


def _render_settings_rulesets():
    st.markdown("##### New ruleset")
    ncol1, ncol2 = st.columns([3, 1], vertical_alignment="bottom")
    new_name = ncol1.text_input("Name", key="rs_new_name", placeholder="Ruleset name")
    if ncol2.button("Create", key="rs_new_btn", width="stretch"):
        clean = new_name.strip()
        if not clean:
            st.warning("Enter a name.")
        elif clean in db.rulesets_all():
            st.error(f"A ruleset named '{clean}' already exists.")
        else:
            db.ruleset_save(clean, GameRules.from_dict(db.settings_get("default_rules")).to_dict())
            st.toast(f"Ruleset created: {clean}")
            st.rerun()

    st.markdown("##### Saved rulesets")
    rulesets = db.rulesets_all()
    if not rulesets:
        st.caption("No rulesets saved yet.")
    for name, rules_dict in rulesets.items():
        slug = "".join(ch if ch.isalnum() else "_" for ch in name)
        with st.expander(name):
            edited = rules_editor(f"rs_{slug}", GameRules.from_dict(rules_dict))
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("Save changes", key=f"rs_save_{slug}", width="stretch"):
                db.ruleset_save(name, edited.to_dict())
                st.toast(f"Ruleset saved: {name}")
            if bcol2.button("Delete", key=f"rs_del_{slug}", width="stretch"):
                db.ruleset_delete(name)
                st.rerun()
