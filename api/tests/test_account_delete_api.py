"""DELETE /users/me: what goes (everything personal), what stays (the games,
under "Deleted player"), and when it's refused (mid-game, open debts)."""

from __future__ import annotations

from uuid import UUID

from app import account_service, auth
from app.config import settings
from app.main import app

from .test_debts_api import _play_taidi_room
from .test_groups_api import _group, _join


async def _settle_all(debtor, creditor):
    for d in (await debtor.get("/debts/me")).json()["owing"]:
        assert (await debtor.post(f"/debts/{d['settlement_id']}/mark-paid")).status_code == 200
        assert (await creditor.post(f"/debts/{d['settlement_id']}/approve")).status_code == 200


async def test_deleting_removes_the_person_and_keeps_their_games(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    room_id = await _play_taidi_room(alice, bob)
    await _settle_all(bob, alice)
    await alice.patch("/users/me/profile", json={"bio": "Plays on Fridays"})
    handle = (await alice.get("/users/me")).json()["username"]

    r = await alice.delete("/users/me")
    assert r.status_code == 204, r.text

    # The token is refused straight away, though it hasn't expired.
    assert (await alice.get("/users/me")).status_code == 401

    # The game is still Bob's record — same result, Alice anonymised.
    state = (await bob.get(f"/rooms/{room_id}/state")).json()
    assert state["members"][alice.user_id]["display_name"] == "Deleted player"
    assert state["balances"][alice.user_id] == 200
    assert (await bob.get("/history/me")).json()["games"][0]["net_cents"] == -200

    # Nothing personal left to find.
    profile = (await bob.get(f"/users/{alice.user_id}/profile")).json()
    assert profile["display_name"] == "Deleted player"
    assert profile["username"] is None and profile.get("bio") is None
    assert (await bob.get(f"/users/by-username/{handle}/profile")).status_code == 404
    assert (await bob.get("/users/search", params={"q": handle})).json()["results"] == []


async def test_refused_mid_game_and_with_open_debts(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")

    r = await alice.post("/rooms")
    assert r.status_code == 201
    r = await alice.delete("/users/me")
    assert r.status_code == 409 and "current game" in r.json()["detail"]
    room_id = (await alice.get("/rooms/active")).json()["room_id"]
    state = (await alice.get(f"/rooms/{room_id}/state")).json()
    await alice.post(f"/rooms/{room_id}/disband", json={"expected_seq": state["seq"]})

    await _play_taidi_room(alice, bob)
    # Either side of an unsettled debt is held up — the other person is
    # still waiting on it.
    for who in (alice, bob):
        r = await who.delete("/users/me")
        assert r.status_code == 409 and "open debt" in r.json()["detail"]
    assert (await alice.get("/users/me")).status_code == 200

    await _settle_all(bob, alice)
    assert (await bob.delete("/users/me")).status_code == 204


async def test_groups_pass_to_the_next_member_and_friendships_go(make_device):
    alice, bob, carol = (
        await make_device("Alice"),
        await make_device("Bob"),
        await make_device("Carol"),
    )
    group = await _group(alice)
    await _join(bob, group)
    solo = await _group(alice, name="Just me")

    await carol.get("/users/me")
    r = await alice.post("/friends/requests", json={"user_id": carol.user_id})
    assert r.status_code == 201
    assert len((await carol.get("/friends")).json()["incoming"]) == 1

    assert (await alice.delete("/users/me")).status_code == 204

    groups = (await bob.get("/groups")).json()["groups"]
    assert [(g["name"], g["is_owner"], g["member_count"]) for g in groups] == [
        ("Friday Night", True, 1)
    ]
    assert (await bob.get(f"/groups/{solo['group_id']}")).status_code == 404
    assert (await carol.get("/friends")).json()["incoming"] == []


async def test_an_old_token_cannot_bring_the_account_back(make_device):
    alice = await make_device("Alice")
    await alice.get("/users/me")
    assert (await alice.delete("/users/me")).status_code == 204

    # As if a second API instance, which never saw the deletion, got the
    # request: the token passes, but the row stays anonymised.
    auth._recently_deleted.clear()
    me = (await alice.get("/users/me")).json()
    assert me["display_name"] == "Deleted player" and me["username"] is None


async def test_supabase_mode_refuses_without_the_service_key(make_device, monkeypatch):
    alice = await make_device("Alice")
    monkeypatch.setattr(settings, "auth_mode", "supabase")
    monkeypatch.setattr(settings, "supabase_service_role_key", None)

    # A dev token isn't a Supabase one, so stand in for the decoded caller.
    async def as_alice():
        return auth.CurrentUser(user_id=UUID(alice.user_id), display_name="Alice", email=None)

    app.dependency_overrides[auth.get_current_user] = as_alice
    try:
        r = await alice.delete("/users/me")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 503 and "isn't set up" in r.json()["detail"]


def test_admin_headers_suit_both_kinds_of_key():
    # New secret keys aren't JWTs: apikey only, never a Bearer token.
    assert account_service._admin_headers("sb_secret_abc") == {"apikey": "sb_secret_abc"}
    # A legacy service_role key is a JWT, and goes on both.
    assert account_service._admin_headers("eyJhbGciOi.x.y") == {
        "apikey": "eyJhbGciOi.x.y",
        "Authorization": "Bearer eyJhbGciOi.x.y",
    }
