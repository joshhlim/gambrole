"""The user directory and friend requests.

Dev-mode tokens carry no email, so search-by-email is exercised by writing a
row directly — matching what backfill_users.py seeds in production.
"""

from __future__ import annotations

from app.db import engine
from app.db import users as users_table
from sqlalchemy import update


async def _register(device):
    """Opening the app is what puts you in the directory."""
    r = await device.get("/users/me")
    assert r.status_code == 200, r.text
    return r.json()


async def _set_email(user_id: str, email: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            update(users_table).where(users_table.c.user_id == user_id).values(email=email)
        )


async def test_opening_the_app_registers_you_with_a_username(make_device):
    """Everyone gets a handle automatically, so no screen ever has to deal
    with a player who hasn't picked one."""
    alice = await make_device("Alice")
    me = await _register(alice)
    assert me["display_name"] == "Alice"
    assert me["user_id"] == alice.user_id
    # Dev tokens carry no email, so it comes from the display name.
    assert me["username"] == "alice"

    # A second Alice can't take the same handle, so she gets a variant.
    other = await make_device("Alice")
    assert (await _register(other))["username"] == "alice2"

    # Re-registering doesn't churn an existing handle.
    assert (await _register(alice))["username"] == "alice"


async def test_username_is_derived_from_the_email_when_there_is_one(make_device):
    alice = await make_device("Alice")
    await _register(alice)
    # Simulate a Supabase account: the address is what people know you by.
    await _set_email(alice.user_id, "jo.shlim@gmail.com")
    bob = await make_device("Bob")
    await _register(bob)

    from app.users_service import suggest_username

    assert suggest_username("jo.shlim@gmail.com", "Josh") == "joshlim"
    assert suggest_username(None, "Qu Zhetao") == "quzhetao"
    assert suggest_username("", "??") == "player"  # nothing usable
    del bob


async def test_username_claim_rules(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)

    r = await alice.put("/users/me/username", json={"username": "  @JoshTheBoss "})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "joshtheboss"  # trimmed, de-@'d, folded

    # Case-insensitively unique — "@JOSHTHEBOSS" must not be a second person.
    r = await bob.put("/users/me/username", json={"username": "JOSHTHEBOSS"})
    assert r.status_code == 409, r.text

    for bad in ("ab", "has spaces", "no-dashes", "way_too_long_a_username_here"):
        r = await bob.put("/users/me/username", json={"username": bad})
        assert r.status_code == 400, f"{bad} should be rejected"

    # Changing your own to the same value is fine (not a self-collision).
    r = await alice.put("/users/me/username", json={"username": "joshtheboss"})
    assert r.status_code == 200, r.text


async def test_search_is_exact_and_never_leaks_email(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)
    await bob.put("/users/me/username", json={"username": "bobby"})
    await _set_email(bob.user_id, "bob@example.com")

    r = await alice.get("/users/search", params={"q": "@BOBBY"})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["display_name"] for x in results] == ["Bob"]
    assert "email" not in results[0]  # findable by address, never told one

    assert (await alice.get("/users/search", params={"q": "bob@example.com"})).json()["results"][0][
        "user_id"
    ] == bob.user_id

    # Exact match only: no prefix, no fuzzy, so the directory can't be walked.
    for q in ("bob", "bobb", "bob@example", "example.com"):
        assert (await alice.get("/users/search", params={"q": q})).json()["results"] == []

    # You never turn up in your own search results.
    await _set_email(alice.user_id, "alice@example.com")
    assert (await alice.get("/users/search", params={"q": "alice@example.com"})).json()[
        "results"
    ] == []


async def test_request_accept_and_unfriend(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)

    r = await alice.post("/friends/requests", json={"user_id": bob.user_id})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"

    a = (await alice.get("/friends")).json()
    b = (await bob.get("/friends")).json()
    assert [e["user"]["display_name"] for e in a["outgoing"]] == ["Bob"]
    assert a["incoming"] == [] and a["friends"] == []
    assert [e["user"]["display_name"] for e in b["incoming"]] == ["Alice"]

    edge_id = b["incoming"][0]["id"]
    # The requester can't accept their own request.
    assert (await alice.post(f"/friends/requests/{edge_id}/accept")).status_code == 404

    assert (await bob.post(f"/friends/requests/{edge_id}/accept")).status_code == 200
    for dev, other in ((alice, "Bob"), (bob, "Alice")):
        body = (await dev.get("/friends")).json()
        assert [e["user"]["display_name"] for e in body["friends"]] == [other]
        assert body["incoming"] == [] and body["outgoing"] == []

    assert (await alice.delete(f"/friends/{bob.user_id}")).status_code == 200
    assert (await bob.get("/friends")).json()["friends"] == []
    # Removal is mutual, and re-adding afterwards works.
    assert (await bob.post("/friends/requests", json={"user_id": alice.user_id})).status_code == 201


async def test_mutual_requests_become_friends_immediately(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)

    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    r = await bob.post("/friends/requests", json={"user_id": alice.user_id})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "accepted"

    for dev in (alice, bob):
        body = (await dev.get("/friends")).json()
        assert len(body["friends"]) == 1
        assert body["incoming"] == [] and body["outgoing"] == []


async def test_request_edge_cases(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)

    assert (
        await alice.post("/friends/requests", json={"user_id": alice.user_id})
    ).status_code == 409
    assert (
        await alice.post(
            "/friends/requests", json={"user_id": "11111111-1111-1111-1111-111111111111"}
        )
    ).status_code == 404

    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    # No spamming the same person.
    assert (await alice.post("/friends/requests", json={"user_id": bob.user_id})).status_code == 409


async def test_declining_leaves_no_trace_and_allows_retry(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    await _register(alice)
    await _register(bob)

    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    edge_id = (await bob.get("/friends")).json()["incoming"][0]["id"]

    # A third party can't touch someone else's request.
    cara = await make_device("Cara")
    await _register(cara)
    assert (await cara.delete(f"/friends/requests/{edge_id}")).status_code == 404

    assert (await bob.delete(f"/friends/requests/{edge_id}")).status_code == 200
    assert (await alice.get("/friends")).json()["outgoing"] == []
    # Nothing records the refusal, so Alice may ask again.
    assert (await alice.post("/friends/requests", json={"user_id": bob.user_id})).status_code == 201


async def test_suggestions_come_from_shared_games_and_drop_once_connected(make_device):
    alice = await make_device("Alice")
    bob = await make_device("Bob")
    stranger = await make_device("Stranger")
    await _register(alice)
    await _register(bob)
    await _register(stranger)

    assert (await alice.get("/friends/suggestions")).json()["results"] == []

    r = await alice.post("/rooms")
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    await bob.get(f"/rooms/by-code/{invite}")
    await bob.post(f"/rooms/{room_id}/join")

    names = [x["display_name"] for x in (await alice.get("/friends/suggestions")).json()["results"]]
    assert names == ["Bob"]  # Stranger shared no room
    assert [
        x["display_name"] for x in (await bob.get("/friends/suggestions")).json()["results"]
    ] == ["Alice"]

    # Once a request is open they stop being a suggestion.
    await alice.post("/friends/requests", json={"user_id": bob.user_id})
    assert (await alice.get("/friends/suggestions")).json()["results"] == []


async def test_username_availability_is_public_and_says_nothing_else(make_device):
    """Runs on the sign-up form, before any account exists — so it can't
    require auth, and must give away nothing but yes/no."""
    alice = await make_device("Alice")
    await _register(alice)
    await alice.put("/users/me/username", json={"username": "takenname"})

    from app.main import app
    from httpx import ASGITransport, AsyncClient

    # No Authorization header at all.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        r = await anon.get("/users/username-available", params={"u": "@TakenName"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["available"] is False
        assert "already taken" in body["reason"]
        # Nothing about who holds it.
        assert "user_id" not in body and "display_name" not in body and "email" not in body

        r = await anon.get("/users/username-available", params={"u": "wideopen"})
        assert r.json() == {"available": True, "reason": None, "username": "wideopen"}

        # Malformed handles report the rule rather than crashing.
        for bad in ("ab", "has space", "no-dash"):
            assert (await anon.get("/users/username-available", params={"u": bad})).json()[
                "available"
            ] is False
