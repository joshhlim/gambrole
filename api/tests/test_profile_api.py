"""Profiles (photo, bio, city, accent), per-account preferences, privacy,
and the public profile page."""

from __future__ import annotations

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


async def _me(device):
    r = await device.get("/users/me")
    assert r.status_code == 200, r.text
    return r.json()


async def _befriend(a, b):
    await _me(a)
    await _me(b)
    await a.post("/friends/requests", json={"user_id": b.user_id})
    edge = (await b.get("/friends")).json()["incoming"][0]["id"]
    await b.post(f"/friends/requests/{edge}/accept")


async def test_edit_profile_fields(make_device):
    alice = await make_device("Alice")
    await _me(alice)
    r = await alice._client.patch(
        "/users/me/profile",
        headers=alice._headers,
        json={"bio": "  Mahjong   at weekends ", "city": "Singapore", "accent": "jade"},
    )
    assert r.status_code == 200, r.text
    me = r.json()
    assert (me["bio"], me["city"], me["accent"]) == ("Mahjong at weekends", "Singapore", "jade")

    r = await alice._client.patch(
        "/users/me/profile", headers=alice._headers, json={"bio": "", "accent": "neon"}
    )
    assert r.status_code == 400  # unknown accent; nothing applied
    r = await alice._client.patch("/users/me/profile", headers=alice._headers, json={"bio": ""})
    assert r.json()["bio"] is None


async def test_photo_upload_serve_and_remove(make_device):
    alice = await make_device("Alice")
    await _me(alice)
    r = await alice.put("/users/me/avatar", content=PNG)
    assert r.status_code == 200, r.text
    url = r.json()["avatar_url"]
    assert url and url.startswith(f"/avatars/{alice.user_id}?v=1&sig=")

    img = await alice._client.get(url)
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png" and img.content == PNG
    assert "immutable" in img.headers["cache-control"]

    # A new photo gets a new URL; a forged signature gets nothing.
    url2 = (await alice.put("/users/me/avatar", content=JPEG)).json()["avatar_url"]
    assert url2 != url and "v=2" in url2
    forged = url2.split("&sig=")[0] + "&sig=" + "0" * 32
    assert (await alice._client.get(forged)).status_code == 404

    assert (await alice.delete("/users/me/avatar")).json()["avatar_url"] is None


async def test_photo_must_be_a_small_real_image(make_device):
    alice = await make_device("Alice")
    await _me(alice)
    r = await alice.put("/users/me/avatar", content=b"<svg>not a photo</svg>")
    assert r.status_code == 400
    r = await alice.put("/users/me/avatar", content=PNG + b"\x00" * (300 * 1024))
    assert r.status_code == 413


async def test_photo_shows_wherever_the_player_does(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    await _me(alice)
    await alice.put("/users/me/avatar", content=PNG)
    profiles = (await bob.post("/users/profiles", json={"ids": [alice.user_id]})).json()
    assert profiles[alice.user_id]["avatar_url"]
    await _befriend(alice, bob)
    friend = (await bob.get("/friends")).json()["friends"][0]["user"]
    assert friend["avatar_url"] == profiles[alice.user_id]["avatar_url"]


async def test_preferences_round_trip_and_validate(make_device):
    alice = await make_device("Alice")
    await _me(alice)
    r = await alice.put(
        "/users/me/preferences",
        json={
            "theme": "dark",
            "currency_symbol": "S$",
            "default_rules": {"taidi": {"card_value_cents": 50}, "mahjong": {"yao_amount": 200}},
        },
    )
    assert r.status_code == 200, r.text
    prefs = r.json()["preferences"]
    assert prefs["theme"] == "dark" and prefs["currency_symbol"] == "S$"
    assert prefs["default_rules"]["taidi"]["card_value_cents"] == 50
    assert prefs["default_rules"]["mahjong"]["yao_amount"] == 200

    # Partial updates merge; null clears one game's default.
    prefs = (
        await alice.put("/users/me/preferences", json={"default_rules": {"taidi": None}})
    ).json()["preferences"]
    assert prefs["theme"] == "dark" and "taidi" not in prefs["default_rules"]

    bad = await alice.put("/users/me/preferences", json={"currency_symbol": "DOGE"})
    assert bad.status_code == 400
    bad = await alice.put(
        "/users/me/preferences", json={"default_rules": {"taidi": {"card_value_cents": -1}}}
    )
    assert bad.status_code == 400


async def test_public_profile_respects_privacy(make_device):
    alice, bob, eve = await make_device("Alice"), await make_device("Bob"), await make_device("Eve")
    await _me(alice)
    await alice._client.patch(
        "/users/me/profile", headers=alice._headers, json={"bio": "hi", "city": "SG"}
    )
    await _befriend(alice, bob)
    await _me(eve)

    # Defaults: bio/city to everyone, stats to friends.
    as_eve = (await eve.get(f"/users/{alice.user_id}/profile")).json()
    assert as_eve["bio"] == "hi" and as_eve["stats"] is None and as_eve["friendship"] == "none"
    as_bob = (await bob.get(f"/users/{alice.user_id}/profile")).json()
    assert as_bob["friendship"] == "friends" and as_bob["stats"]["total_sessions"] == 0

    await alice.put(
        "/users/me/privacy", json={"profile_visibility": "friends", "stats_visibility": "nobody"}
    )
    assert (await eve.get(f"/users/{alice.user_id}/profile")).json()["bio"] is None
    as_bob = (await bob.get(f"/users/{alice.user_id}/profile")).json()
    assert as_bob["bio"] == "hi" and as_bob["stats"] is None
    assert (await bob.get(f"/stats/facts/{alice.user_id}")).status_code == 403

    me = (await alice.get(f"/users/{alice.user_id}/profile")).json()
    assert me["friendship"] == "self" and me["stats"] is not None

    username = (await _me(alice))["username"]
    by_handle = await eve.get(f"/users/by-username/@{username}/profile")
    assert by_handle.status_code == 200 and by_handle.json()["user_id"] == alice.user_id


async def test_search_opt_out(make_device):
    alice, bob = await make_device("Alice"), await make_device("Bob")
    username = (await _me(alice))["username"]
    await _me(bob)
    assert (await bob.get("/users/search", params={"q": username})).json()["results"]
    await alice.put("/users/me/privacy", json={"searchable": False})
    assert (await bob.get("/users/search", params={"q": username})).json()["results"] == []
