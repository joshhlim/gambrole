import { test, expect } from "@playwright/test";
import { amountFor, joinByCode, login, openNewRoom, players, submitNewRoom } from "./helpers";

/**
 * Drives a Mahjong game across four separate browser contexts, mirroring
 * full-game.spec.ts's convergence-testing pattern for Taidi.
 */

test("the 5/1 半 preset fills in its stakes table", async ({ page }) => {
  await login(page, `Preset-${Date.now().toString(36)}`);
  await openNewRoom(page, "mahjong");

  await page.getByTestId("mahjong-preset-5/1-半").click();

  await expect(page.getByTestId("rule-base")).toHaveValue("500");
  await expect(page.getByTestId("rule-yao")).toHaveValue("3");
  await expect(page.getByTestId("rule-gang")).toHaveValue("3");
  await expect(page.getByTestId("rule-zimo-bonus")).toHaveValue("5");
  await expect(page.getByTestId("rule-klppdd")).toHaveValue("5");
  await expect(page.getByTestId("rule-tai-1-hu")).toHaveValue("4");
  await expect(page.getByTestId("rule-tai-1-zimo")).toHaveValue("2");
  await expect(page.getByTestId("rule-tai-7-hu")).toHaveValue("256");
  await expect(page.getByTestId("rule-tai-7-zimo")).toHaveValue("128");
  await expect(page.getByTestId("tai-row-add")).toBeVisible();

  // Out-of-range or non-integer values keep Create disabled.
  await page.getByTestId("rule-yao").fill("-2");
  await expect(page.getByTestId("create-room-btn")).toBeDisabled();
  await page.getByTestId("rule-yao").fill("3");
  await page.getByTestId("rule-tai-2-hu").fill("2.5");
  await expect(page.getByTestId("create-room-btn")).toBeDisabled();
  await page.getByTestId("rule-tai-2-hu").fill("8");
  await expect(page.getByTestId("create-room-btn")).toBeEnabled();
});

test("a full hand across four simulated devices", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob", "Cara", "Dan"]);
  const [alice, bob, cara, dan] = pages;

  try {
    await openNewRoom(alice, "mahjong");
    const inviteCode = await submitNewRoom(alice);
    await expect(alice.getByTestId("rules-summary")).toContainText("base 300");

    for (const p of [bob, cara, dan]) await joinByCode(p, inviteCode);
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("lobby-member")).toHaveCount(4, { timeout: 10_000 });
    }

    // Host starts; everyone transitions to the live table with the wind/dealer
    // indicator and the action buttons.
    await alice.getByTestId("start-game-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });
      await expect(p.getByTestId("dealer-seat")).toHaveAttribute("data-wind", "1");
    }

    // Alice YAOs herself (咬自己): each of the other 3 pays 2 chips. Displayed
    // amounts are chip stacks (base 300 + net), not raw dollars.
    await alice.getByTestId("yao-btn").click();
    await alice.getByTestId("pick-seat-0").click();
    await alice.getByTestId("yao-ming-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(amountFor(p, "Alice")).toHaveText("306", { timeout: 10_000 }); // 300 + 3*2
    }

    // Bob declares ANGANG — double-tapped, which must still charge once:
    // each of the other 3 pays gang_chips*2=4. Bob already paid 2 into
    // Alice's YAO, so his net is -2+12=10.
    await bob.getByTestId("gang-btn").click();
    await bob.getByTestId("pick-angang").dblclick();
    for (const p of [alice, bob, cara, dan]) {
      await expect(amountFor(p, "Bob")).toHaveText("310", { timeout: 10_000 }); // 300 - 2 + 3*4
    }

    // Cara gangs off Dan (seat 3) — in GangFlow the seat tap *is* the
    // submit, so this double-tap is the one that used to charge twice.
    // Dan alone pays gang_chips*3 = 6.
    await cara.getByTestId("gang-btn").click();
    await cara.getByTestId("pick-seat-3").dblclick();
    for (const p of [alice, bob, cara, dan]) {
      await expect(amountFor(p, "Cara")).toHaveText("300", { timeout: 10_000 }); // 300 - 2 - 4 + 6
      await expect(amountFor(p, "Dan")).toHaveText("288", { timeout: 10_000 }); // 300 - 2 - 4 - 6
    }

    // Dan directly HUs off Cara (seat 2) at 2 tai — closes the hand. Dan
    // (seat 3) isn't the dealer (seat 0), so the dealer rotates for hand 2
    // regardless of the earlier gangs.
    await dan.getByTestId("hu-btn").click();
    await dan.getByTestId("pick-seat-2").click();
    await dan.getByTestId("tai-plus").click();
    await dan.getByTestId("confirm-hu-btn").click();

    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("dealer-seat")).toHaveAttribute("data-dealer-seat", "1", {
        timeout: 10_000,
      });
      // Back to the action buttons for hand 2 on every device.
      await expect(p.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });
    }
    // 3/6 半 at 2 tai: hu = 7.
    await expect(amountFor(alice, "Dan")).toHaveText("295"); // 288 + 7
    await expect(amountFor(alice, "Cara")).toHaveText("293"); // 300 - 7
    await expect(
      alice.locator('[data-testid="standing-row"][data-player^="Bob"]'),
    ).toHaveAttribute("data-dealer", "true");

    // No Win asks first. With no gang this hand, the dealer stays on Bob.
    await cara.getByTestId("no-win-btn").click();
    await cara.getByTestId("cancel-no-win-btn").click();
    await cara.getByTestId("no-win-btn").click();
    await expect(alice.getByTestId("dealer-seat")).toHaveAttribute("data-hand", "2");
    await cara.getByTestId("confirm-no-win-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("dealer-seat")).toHaveAttribute("data-hand", "3", {
        timeout: 10_000,
      });
      await expect(p.getByTestId("dealer-seat")).toHaveAttribute("data-dealer-seat", "1");
    }

    // Only the host can end, and only after confirming.
    await expect(bob.getByTestId("end-game-btn")).toHaveCount(0);
    await alice.getByTestId("end-game-btn").click();
    await alice.getByTestId("confirm-end-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });
      await expect(p.getByTestId("standing-row")).toHaveCount(4);
    }
  } finally {
    await close();
  }
});

test("zimo bonus and KLPPDD toggles add on top of the tai payout", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob", "Cara", "Dan"]);
  const [alice, bob, cara, dan] = pages;

  try {
    // Both bonuses set on the form, and sent with the create call.
    await openNewRoom(alice, "mahjong");
    await alice.getByTestId("rule-zimo-bonus").fill("5");
    await alice.getByTestId("rule-klppdd").fill("10");
    const inviteCode = await submitNewRoom(alice);
    await expect(alice.getByTestId("rules-summary")).toContainText("klppdd 10");

    for (const p of [bob, cara, dan]) await joinByCode(p, inviteCode);
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("lobby-member")).toHaveCount(4, { timeout: 10_000 });
    }

    await alice.getByTestId("start-game-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(p.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });
    }

    // Alice self-draws at 1 tai (default table: hu=4/zimo=4) with the zimo
    // bonus (5) and KLPPDD (10) both on: each of the other 3 pays
    // 4 + 5 + 10 = 19.
    await alice.getByTestId("hu-btn").click();
    await alice.getByTestId("pick-seat-0").click();
    await alice.getByTestId("zimo-bonus-toggle").click();
    await alice.getByTestId("klppdd-toggle").click();
    await alice.getByTestId("confirm-hu-btn").click();
    for (const p of [alice, bob, cara, dan]) {
      await expect(amountFor(p, "Alice")).toHaveText("357", { timeout: 10_000 }); // 300 + 3*19
      await expect(amountFor(p, "Bob")).toHaveText("281", { timeout: 10_000 }); // 300 - 19
    }

    // Cara's phone loses the server for a while: it keeps showing hand 2,
    // quietly marked as reconnecting.
    await cara.route("**/rooms/*/state", (r) => r.abort());
    await expect(cara.getByTestId("reconnecting")).toBeVisible({ timeout: 10_000 });

    // Meanwhile Bob directly HUs off Cara (seat 2) at 1 tai with KLPPDD on
    // (no zimo bonus option for a direct win): Cara alone pays 4 + 3*10 = 34.
    await bob.getByTestId("hu-btn").click();
    await bob.getByTestId("pick-seat-2").click();
    await expect(bob.getByTestId("zimo-bonus-toggle")).toHaveCount(0);
    await bob.getByTestId("klppdd-toggle").click();
    await bob.getByTestId("confirm-hu-btn").click();
    for (const p of [alice, bob, dan]) {
      await expect(amountFor(p, "Bob")).toHaveText("315", { timeout: 10_000 }); // 281 + 34
      await expect(amountFor(p, "Cara")).toHaveText("247", { timeout: 10_000 }); // 281 - 34
      await expect(p.getByTestId("dealer-seat")).toHaveAttribute("data-hand", "3");
    }

    // Cara, still looking at hand 2, declares a YAO. It names hand 2, which
    // is over — so it's refused (not retried onto hand 3), and her screen
    // catches up from the refusal.
    await expect(cara.getByTestId("dealer-seat")).toHaveAttribute("data-hand", "2");
    await cara.getByTestId("yao-btn").click();
    await cara.getByTestId("pick-seat-2").click();
    await cara.getByTestId("yao-ming-btn").click();
    await expect(cara.getByTestId("room-banner")).toHaveText("That hand already moved on.", {
      timeout: 10_000,
    });
    await expect(cara.getByTestId("dealer-seat")).toHaveAttribute("data-hand", "3");
    await cara.unroute("**/rooms/*/state");
    for (const p of [alice, bob, cara, dan]) {
      await expect(amountFor(p, "Cara")).toHaveText("247", { timeout: 10_000 }); // no YAO landed
      await expect(amountFor(p, "Bob")).toHaveText("315");
    }
    await expect(cara.getByTestId("reconnecting")).toHaveCount(0, { timeout: 20_000 });
  } finally {
    await close();
  }
});

test("the table fits a 320px phone", async ({ browser }) => {
  const contexts = await Promise.all(
    [0, 1, 2, 3].map((i) =>
      browser.newContext(i === 0 ? { viewport: { width: 320, height: 640 } } : {}),
    ),
  );
  const pages = await Promise.all(contexts.map((c) => c.newPage()));
  const uniq = Date.now().toString(36);
  try {
    await Promise.all(
      pages.map((p, i) => login(p, `${["Alexandrina", "Bob", "Cara", "Dan"][i]}-${uniq}`)),
    );
    const [small, ...rest] = pages;
    await openNewRoom(small, "mahjong");
    const code = await submitNewRoom(small);
    for (const p of rest) await joinByCode(p, code);
    await expect(small.getByTestId("lobby-member")).toHaveCount(4, { timeout: 10_000 });
    await small.getByTestId("start-game-btn").click();
    await expect(small.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });

    const cards = small.getByTestId("standing-row");
    await expect(cards).toHaveCount(4);
    const widths = new Set<number>();
    for (const box of await Promise.all((await cards.all()).map((c) => c.boundingBox()))) {
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(320);
      widths.add(Math.round(box!.width));
    }
    // Every card the same size, whatever the names.
    expect(widths.size).toBe(1);
    expect(await small.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  } finally {
    await Promise.all(contexts.map((c) => c.close()));
  }
});

test("a member can leave a mahjong lobby, and the host can disband it", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob"]);
  const [alice, bob] = pages;

  try {
    await openNewRoom(alice, "mahjong");
    const inviteCode = await submitNewRoom(alice);

    await joinByCode(bob, inviteCode);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });

    // The back arrow only minimises — Bob is still in the room after it.
    await bob.getByTestId("back-btn").click();
    await expect(bob).toHaveURL("/");
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2);
    await bob.getByTestId("rejoin-room-btn").click();
    await expect(bob.getByTestId("leave-room-btn")).toBeVisible({ timeout: 10_000 });

    await bob.getByTestId("leave-room-btn").click();
    await expect(bob).toHaveURL("/");
    await expect(alice.getByTestId("lobby-member")).toHaveCount(1, { timeout: 10_000 });

    await alice.getByTestId("disband-room-btn").click();
    await alice.getByTestId("confirm-disband-btn").click();
    await expect(alice).toHaveURL("/");
  } finally {
    await close();
  }
});
