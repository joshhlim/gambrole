import { test, expect, type Page } from "@playwright/test";

/**
 * Drives a full game across three separate browser contexts — the real
 * proof of the Phase 2 vertical slice ("a live room on two phones"), not
 * just that the API or the state machine work in isolation.
 */

async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByTestId("display-name-input").fill(name);
  await page.getByTestId("continue-btn").click();
  await expect(page.getByText(`Signed in as ${name}`)).toBeVisible();
}

/** Creates a Taidi room with a custom card value, proving the rules chosen
 * on /new actually reach the room (not just that *some* rules apply). */
async function createTaidiRoom(page: Page, cardValueDollars: string) {
  await page.getByTestId("new-room-btn").click();
  await expect(page).toHaveURL(/\/new/);
  await page.getByTestId("game-tile-taidi").click();
  await page.getByTestId("rule-card-value").fill(cardValueDollars);
  await page.getByTestId("create-room-btn").click();
  await expect(page).toHaveURL(/\/room\//);
}

test("a full game across three simulated devices", async ({ browser }) => {
  const aliceCtx = await browser.newContext();
  const bobCtx = await browser.newContext();
  const charlieCtx = await browser.newContext();
  const alice = await aliceCtx.newPage();
  const bob = await bobCtx.newPage();
  const charlie = await charlieCtx.newPage();

  try {
    const uniq = Date.now().toString(36);
    await login(alice, `Alice-${uniq}`);
    await login(bob, `Bob-${uniq}`);
    await login(charlie, `Charlie-${uniq}`);

    // Alice creates a Taidi room at $1.00/card (not the $0.20 default) and
    // shares the code — the custom value is verified against an exact
    // expected balance once round 1 resolves, below.
    await createTaidiRoom(alice, "1.00");
    const inviteCode = (await alice.getByTestId("invite-code").textContent())?.trim();
    expect(inviteCode).toMatch(/^[A-Z0-9]{6}$/);

    // Bob and Charlie join by code from their own devices
    for (const p of [bob, charlie]) {
      await p.getByTestId("room-code-input").fill(inviteCode!);
      await p.getByTestId("join-room-btn").click();
      await expect(p).toHaveURL(/\/room\//);
    }

    // All three converge on seeing 3 members (proves polling + join worked
    // across independent browser contexts, not just within one page)
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("lobby-member")).toHaveCount(3, { timeout: 10_000 });
    }

    // Host starts the game; everyone transitions to the live table
    await alice.getByTestId("start-game-btn").click();
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    }

    // Alice claims the win for round 1
    await alice.getByTestId("win-btn").click();
    await expect(alice.getByTestId("waiting-text")).toBeVisible({ timeout: 10_000 });

    // Bob and Charlie each get prompted for their own card count
    for (const p of [bob, charlie]) {
      await expect(p.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    }
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

    // Balances updated and are visible to everyone, not just the actor.
    // At the default rules, $1.00/card, Alice=0, Bob=3, Charlie=11:
    //   Bob pays  3 x1 (cards) +  2 (base)                     = $5
    //   Charlie pays 11 x2 (cards) + (11-3) x2 (diff, to Bob) + 2 (base) = $40
    //   Alice receives cards+base = $29.00 exactly — the custom $1.00/card
    //   value only shows up in a number this large, proving it was applied.
    for (const p of [alice, bob, charlie]) {
      const aliceAmount = p
        .locator('[data-testid="standing-row"][data-player^="Alice-"] [data-testid="standing-amount"]')
        .first();
      await expect(aliceAmount).toHaveText("$29.00", { timeout: 10_000 });
    }

    // Bob claims a special hand mid-round — settles immediately for everyone
    const bobBefore = await bob
      .locator('[data-testid="standing-row"][data-player^="Bob-"] [data-testid="standing-amount"]')
      .first()
      .textContent();
    await bob.getByTestId("special-hand-btn").click();
    await expect(
      charlie
        .locator('[data-testid="standing-row"][data-player^="Bob-"] [data-testid="standing-amount"]')
        .first(),
    ).not.toHaveText(bobBefore ?? "", { timeout: 10_000 });

    // Anyone can end the game — everyone sees the final-stats screen,
    // from their own device, not just the player who clicked End Game.
    await charlie.getByTestId("end-game-btn").click();
    for (const p of [alice, bob, charlie]) {
      await expect(p.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });
      await expect(p.getByText(/rounds? played/)).toBeVisible();
      await expect(p.getByTestId("standing-row")).toHaveCount(3);
    }
  } finally {
    await aliceCtx.close();
    await bobCtx.close();
    await charlieCtx.close();
  }
});

test("poker shows as not-available yet", async ({ page }) => {
  await login(page, `Dana-${Date.now().toString(36)}`);
  await page.getByTestId("new-room-btn").click();
  await expect(page).toHaveURL(/\/new/);

  await page.getByTestId("game-tile-poker").click();
  await expect(page.getByTestId("not-available")).toBeVisible();
  await page.getByText("Choose another game").click();
  await expect(page.getByTestId("game-tile-poker")).toBeVisible();
});

test("my stats shows an empty state for a brand-new player", async ({ page }) => {
  await login(page, `Eve-${Date.now().toString(36)}`);
  await page.getByTestId("my-stats-btn").click();
  await expect(page).toHaveURL(/\/stats/);
  await expect(page.getByTestId("stats-tab-overview")).toBeVisible();
  await expect(page.getByTestId("stats-empty")).toBeVisible();
});

test("a member can leave a lobby, and the host can disband it", async ({ browser }) => {
  const aliceCtx = await browser.newContext();
  const bobCtx = await browser.newContext();
  const alice = await aliceCtx.newPage();
  const bob = await bobCtx.newPage();

  try {
    const uniq = Date.now().toString(36);
    await login(alice, `Alice-${uniq}`);
    await login(bob, `Bob-${uniq}`);

    await createTaidiRoom(alice, "0.20");
    const inviteCode = (await alice.getByTestId("invite-code").textContent())?.trim();

    await bob.getByTestId("room-code-input").fill(inviteCode!);
    await bob.getByTestId("join-room-btn").click();
    await expect(bob).toHaveURL(/\/room\//);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });

    // Bob joined the wrong room and leaves — Alice sees the lobby shrink
    // back to just herself, from her own device.
    await bob.getByTestId("leave-room-btn").click();
    await expect(bob).toHaveURL("/");
    await expect(alice.getByTestId("lobby-member")).toHaveCount(1, { timeout: 10_000 });

    // Alice decides not to play after all and disbands the room.
    await alice.getByTestId("disband-room-btn").click();
    await expect(alice).toHaveURL("/");
  } finally {
    await aliceCtx.close();
    await bobCtx.close();
  }
});
