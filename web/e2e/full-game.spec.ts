import { test, expect } from "@playwright/test";
import {
  amountFor,
  joinByCode,
  login,
  openNewRoom,
  players,
  submitNewRoom,
} from "./helpers";

/**
 * Drives a full game across three separate browser contexts — the real
 * proof of the Phase 2 vertical slice ("a live room on two phones"), not
 * just that the API or the state machine work in isolation.
 */

test("a full game across three simulated devices", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob", "Charlie"]);
  const [alice, bob, charlie] = pages;

  try {
    // Alice creates a Taidi room at $1.00/card and 4 cards per special hand
    // (neither is the default). Rules go up with the create call now, so the
    // lobby can already show them.
    await openNewRoom(alice, "taidi");
    await alice.getByTestId("rule-card-value").fill("1.00");
    await alice.getByTestId("rule-special-cards").fill("4");
    const inviteCode = await submitNewRoom(alice);
    await expect(alice.getByTestId("rules-summary")).toContainText("$1.00/card");
    await expect(alice.getByTestId("rules-summary")).toContainText("special +4");

    // Bob and Charlie join by code from their own devices
    for (const p of [bob, charlie]) await joinByCode(p, inviteCode);

    // All three converge on seeing 3 members (proves polling + join worked
    // across independent browser contexts, not just within one page)
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("lobby-member")).toHaveCount(3, { timeout: 10_000 });
    }

    // Host starts the game with no rules in the start call; the room runs on
    // the ones chosen at creation.
    await alice.getByTestId("start-game-btn").click();
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
      await expect(p.getByTestId("rules-summary")).toContainText("$1.00/card");
    }

    // Alice claims the win for round 1 — a double-tap must still be one claim.
    await alice.getByTestId("win-btn").dblclick();
    await expect(alice.getByTestId("waiting-text")).toBeVisible({ timeout: 10_000 });

    // Bob and Charlie each get prompted for their own card count
    for (const p of [bob, charlie]) {
      await expect(p.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    }
    // Not a whole number: the form won't send it.
    await bob.getByTestId("cards-input").fill("1.5");
    await expect(bob.getByTestId("submit-cards-btn")).toBeDisabled();
    await bob.getByTestId("cards-input").fill("3");
    await bob.getByTestId("submit-cards-btn").click();
    // Charlie hasn't submitted yet — round should still be collecting for Bob
    await expect(bob.getByTestId("waiting-text")).toBeVisible({ timeout: 10_000 });

    await charlie.getByTestId("cards-input").fill("11");
    await charlie.getByTestId("submit-cards-btn").click();

    // Round resolves automatically once the last count lands — everyone
    // should see round 2's Win button appear, on their own device.
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    }

    // At $1.00/card, base 2, x2 at 10+, difference payouts; Alice=0, Bob=3,
    // Charlie=11:
    //   Bob pays Alice 3 (cards) + 2 (base)                          = $5
    //   Charlie pays Alice 11x2 + 2 = $24, and Bob (11-3)x2 = $16     = $40
    //   Alice +$29, Bob -5+16 = +$11, Charlie -$40.
    for (const p of [alice, bob, charlie]) {
      await expect(amountFor(p, "Alice-")).toHaveText("$29.00", { timeout: 10_000 });
      await expect(amountFor(p, "Bob-")).toHaveText("$11.00", { timeout: 10_000 });
      await expect(amountFor(p, "Charlie-")).toHaveText("-$40.00", { timeout: 10_000 });
    }

    // Bob claims a special hand (confirm-gated): 4 cards x $1.00 from each
    // of the other two, settled immediately for everyone.
    await bob.getByTestId("special-hand-btn").click();
    await bob.getByTestId("confirm-special-btn").click();
    for (const p of [alice, bob, charlie]) {
      await expect(amountFor(p, "Bob-")).toHaveText("$19.00", { timeout: 10_000 });
      await expect(amountFor(p, "Alice-")).toHaveText("$25.00", { timeout: 10_000 });
      await expect(amountFor(p, "Charlie-")).toHaveText("-$44.00", { timeout: 10_000 });
    }

    // Only the host can end the game, and only after confirming.
    await expect(charlie.getByTestId("end-game-btn")).toHaveCount(0);
    await alice.getByTestId("end-game-btn").click();
    await alice.getByTestId("confirm-end-btn").click();
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });
      await expect(p.getByText(/rounds? played/)).toBeVisible();
      await expect(p.getByTestId("standing-row")).toHaveCount(3);
    }
  } finally {
    await close();
  }
});

test("the rules form refuses values the API would reject", async ({ page }) => {
  await login(page, `Rules-${Date.now().toString(36)}`);
  await openNewRoom(page, "taidi");
  const create = page.getByTestId("create-room-btn");
  await expect(create).toBeEnabled();

  await page.getByTestId("rule-card-value").fill("-1");
  await expect(create).toBeDisabled();
  await page.getByTestId("rule-card-value").fill("0.2");
  await expect(create).toBeEnabled();

  await page.getByTestId("rule-base-cards").fill("1.5");
  await expect(create).toBeDisabled();
  await page.getByTestId("rule-base-cards").fill("2");

  // x3 below x2 makes no sense.
  await page.getByTestId("rule-triple").fill("5");
  await expect(create).toBeDisabled();
  await page.getByTestId("rule-triple").fill("13");
  await expect(create).toBeEnabled();
});

test("poker shows as not-available yet", async ({ page }) => {
  await login(page, `Dana-${Date.now().toString(36)}`);
  await openNewRoom(page, "poker");
  await expect(page.getByTestId("not-available")).toBeVisible();
  await page.getByText("Choose another game").click();
  await expect(page.getByTestId("game-tile-poker")).toBeVisible();
});

test("my stats shows an empty state for a brand-new player", async ({ page }) => {
  await login(page, `Eve-${Date.now().toString(36)}`);
  await page.getByTestId("account-btn").click();
  await page.getByTestId("menu-stats").click();
  await expect(page).toHaveURL(/\/stats/);
  await expect(page.getByTestId("stats-empty")).toBeVisible();
});

test("top-bar dropdowns fit a 320px phone", async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 320, height: 640 } });
  const page = await ctx.newPage();
  try {
    await login(page, `Narrow-${Date.now().toString(36)}`);
    for (const [btn, panel] of [
      ["account-btn", "account-menu"],
      ["bell-btn", "bell-panel"],
    ]) {
      await page.getByTestId(btn).click();
      const box = await page.getByTestId(panel).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(320);
      await page.keyboard.press("Escape");
    }
  } finally {
    await ctx.close();
  }
});

test("a member can leave a lobby, and the host can disband it", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob"]);
  const [alice, bob] = pages;

  try {
    await openNewRoom(alice, "taidi");
    const inviteCode = await submitNewRoom(alice);

    await joinByCode(bob, inviteCode);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });

    // Bob joined the wrong room and leaves — Alice sees the lobby shrink
    // back to just herself, from her own device.
    await bob.getByTestId("leave-room-btn").click();
    await expect(bob).toHaveURL("/");
    await expect(alice.getByTestId("lobby-member")).toHaveCount(1, { timeout: 10_000 });

    // Alice decides not to play after all and disbands the room.
    await alice.getByTestId("disband-room-btn").click();
    await alice.getByTestId("confirm-disband-btn").click();
    await expect(alice).toHaveURL("/");
  } finally {
    await close();
  }
});
