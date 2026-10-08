"""Mahjong in dollars: rules and balances are cents, and a client from
before the switch (sending chip-denominated `*_chips` rules) still plays at
the same money rather than 1/50th of it."""

from __future__ import annotations

import pytest


async def _mahjong_with_rules(make_device, rules):
    devices = [await make_device(name) for name in ("Alice", "Bob", "Cara", "Dan")]
    alice = devices[0]
    r = await alice.post("/rooms", json={"game_type": "mahjong", "rules": rules})
    assert r.status_code == 201, r.text
    room_id, invite = r.json()["room_id"], r.json()["invite_code"]
    for d in devices[1:]:
        await d.get(f"/rooms/by-code/{invite}")
        r = await d.post(f"/rooms/{room_id}/mahjong/join")
    st = r.json()
    r = await alice.post(f"/rooms/{room_id}/mahjong/start", json={"expected_seq": st["seq"]})
    assert r.status_code == 200, r.text
    return room_id, devices, r.json()


@pytest.mark.parametrize(
    "rules",
    [
        {"cents_per_unit": 1, "yao_amount": 100, "gang_amount": 100},  # current client
        {"yao_amount": 100, "gang_amount": 100},  # current client, unit omitted
        {"base_chips": 300, "yao_chips": 2, "gang_chips": 2},  # client from before dollars
    ],
)
async def test_a_yao_costs_a_dollar_however_the_rules_were_sent(make_device, rules):
    room_id, (alice, bob, _cara, _dan), st = await _mahjong_with_rules(make_device, rules)
    r = await alice.post(
        f"/rooms/{room_id}/mahjong/yao",
        json={"expected_seq": st["seq"], "hand_no": 1, "target_seat": 0},
    )
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["balances"][alice.user_id] == 300
    assert state["balances"][bob.user_id] == -100


async def test_settlements_are_in_cents(make_device):
    room_id, (alice, bob, _cara, _dan), st = await _mahjong_with_rules(make_device, {})
    st = (
        await alice.post(
            f"/rooms/{room_id}/mahjong/hu",
            json={
                "expected_seq": st["seq"],
                "hand_no": 1,
                "mode": "direct",
                "target_seat": 1,
                "tai": 1,
            },
        )
    ).json()
    await alice.post(f"/rooms/{room_id}/mahjong/end", json={"expected_seq": st["seq"]})
    owed = (await alice.get("/debts/me")).json()["owed"]
    assert [d["amount_cents"] for d in owed] == [200]
    del bob
