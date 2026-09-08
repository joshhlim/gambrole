import { test, expect, type Page } from "@playwright/test";

async function login(page: Page, name: string) {
  await page.goto("/");
  await page.getByTestId("display-name-input").fill(name);
  await page.getByTestId("continue-btn").click();
  await expect(page.getByText(`Signed in as ${name}`)).toBeVisible();
}

test("stats dashboard reflects a finished Taidi game and a finished Mahjong game", async ({
  browser,
}) => {
  const contexts = await Promise.all([0, 1, 2, 3].map(() => browser.newContext()));
  const [alice, bob, cara, dan] = await Promise.all(contexts.map((c) => c.newPage()));

  try {
    const uniq = Date.now().toString(36);
    await login(alice, `Alice-${uniq}`);
    await login(bob, `Bob-${uniq}`);
    await login(cara, `Cara-${uniq}`);
    await login(dan, `Dan-${uniq}`);

    // --- Taidi: Alice wins, Bob submits 1 card (below the double band at
    // default rules: card_value_cents=20, base_cards=2) -> Bob pays Alice
    // 1*1*20 (cards) + 2*20 (base) = 60 cents.
    await alice.getByTestId("new-room-btn").click();
    await alice.getByTestId("game-tile-taidi").click();
    await alice.getByTestId("create-room-btn").click();
    await expect(alice).toHaveURL(/\/room\//);
    const taidiInvite = (await alice.getByTestId("invite-code").textContent())?.trim();

    await bob.getByTestId("room-code-input").fill(taidiInvite!);
    await bob.getByTestId("join-room-btn").click();
    await expect(bob).toHaveURL(/\/room\//);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });

    await alice.getByTestId("start-game-btn").click();
    await expect(alice.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("win-btn").click();
    await expect(bob.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    await bob.getByTestId("cards-input").fill("1");
    await bob.getByTestId("submit-cards-btn").click();
    await expect(alice.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("end-game-btn").click();
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("back-to-home-btn").click();
    await expect(alice).toHaveURL("/");

    await bob.goto("/");

    // --- Mahjong: Alice HUs directly off Bob (seat 1) at 1 tai against the
    // default "3/6 半" table (hu(1)=4) -> Bob pays Alice 4 chips.
    await alice.getByTestId("new-room-btn").click();
    await alice.getByTestId("game-tile-mahjong").click();
    await alice.getByTestId("create-room-btn").click();
    await expect(alice).toHaveURL(/\/room\//);
    const mjInvite = (await alice.getByTestId("invite-code").textContent())?.trim();

    for (const p of [bob, cara, dan]) {
      await p.getByTestId("room-code-input").fill(mjInvite!);
      await p.getByTestId("join-room-btn").click();
      await expect(p).toHaveURL(/\/room\//);
    }
    await expect(alice.getByTestId("lobby-member")).toHaveCount(4, { timeout: 10_000 });

    await alice.getByTestId("start-game-btn").click();
    await expect(alice.getByTestId("hu-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("hu-btn").click();
    await alice.getByTestId("pick-seat-1").click();
    await alice.getByTestId("confirm-hu-btn").click();
    await alice.getByTestId("end-game-btn").click();
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    // --- Stats: 60 cents (taidi) + 4 chips * 50 cents/chip (mahjong) = $2.60.
    await alice.goto("/stats");
    await expect(alice.getByTestId("overview-total")).toHaveText("$2.60", { timeout: 10_000 });
    await expect(alice.getByTestId("overview-taidi-cents")).toHaveText("$0.60");
    await expect(alice.getByTestId("overview-mahjong-cents")).toHaveText("$2.00");
    await expect(alice.getByTestId("overview-streak")).toHaveText("2 wins");

    await alice.getByTestId("stats-tab-taidi").click();
    await expect(alice.getByTestId("taidi-round-win-rate")).toHaveText("100%");
    await expect(alice.getByTestId("taidi-profit-rate")).toHaveText("100%");
    await expect(alice.getByTestId("taidi-double-rate")).toHaveText("0%");

    await alice.getByTestId("stats-tab-mahjong").click();
    await expect(alice.getByTestId("mahjong-hu-rate")).toHaveText("100%");
    await expect(alice.getByTestId("mahjong-dealer-win-rate")).toHaveText("100%");

    // --- Bob's perspective: both games are losses.
    await bob.goto("/stats");
    await expect(bob.getByTestId("overview-total")).toHaveText("-$2.60", { timeout: 10_000 });
    await expect(bob.getByTestId("overview-streak")).toHaveText("2 losses");
  } finally {
    await Promise.all(contexts.map((c) => c.close()));
  }
});
