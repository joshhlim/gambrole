import { test, expect } from "@playwright/test";
import { joinByCode, openNewRoom, players, submitNewRoom } from "./helpers";

test("stats dashboard reflects a finished Taidi game and a finished Mahjong game", async ({
  browser,
}) => {
  const { pages, close } = await players(browser, ["Alice", "Bob", "Cara", "Dan", "Eve"]);
  const [alice, bob, cara, dan, eve] = pages;

  try {
    // --- Taidi: Alice wins, Bob submits 1 card (below the double band at
    // default rules: card_value_cents=20, base_cards=2) -> Bob pays Alice
    // 1*1*20 (cards) + 2*20 (base) = 60 cents.
    await openNewRoom(alice, "taidi");
    const taidiInvite = await submitNewRoom(alice);
    const taidiUrl = alice.url();

    await joinByCode(bob, taidiInvite);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });

    await alice.getByTestId("start-game-btn").click();
    await expect(alice.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("win-btn").click();
    await expect(bob.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    await bob.getByTestId("cards-input").fill("1");
    await bob.getByTestId("submit-cards-btn").click();
    await expect(alice.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("end-game-btn").click();
    await alice.getByTestId("confirm-end-btn").click();
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    // Someone who was never in it can't read a finished room — and gets
    // told so, rather than a crash or an endless "Loading…".
    await eve.goto(taidiUrl);
    await expect(eve.getByTestId("room-problem")).toHaveText("You're not in this game.", {
      timeout: 10_000,
    });

    // --- Mahjong: Alice HUs directly off Bob (seat 1) at 1 tai against the
    // default "3/6 半" table (hu(1)=$2.00) -> Bob pays Alice $2.00.
    await openNewRoom(alice, "mahjong");
    const mjInvite = await submitNewRoom(alice);

    for (const p of [bob, cara, dan]) await joinByCode(p, mjInvite);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(4, { timeout: 10_000 });

    await alice.getByTestId("start-game-btn").click();
    await expect(alice.getByTestId("hu-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("hu-btn").click();
    await alice.getByTestId("pick-seat-1").click();
    await alice.getByTestId("confirm-hu-btn").click();
    await expect(alice.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("end-game-btn").click();
    await alice.getByTestId("confirm-end-btn").click();
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    // --- Stats: $0.60 (taidi) + $2.00 (mahjong) = $2.60.
    await alice.goto("/stats");
    await expect(alice.getByTestId("overview-total")).toHaveText("$2.60", { timeout: 10_000 });
    await expect(alice.getByTestId("overview-sessions")).toHaveText("2");
    await expect(alice.getByTestId("overview-best-game")).toHaveText("Mahjong");
    await expect(alice.getByTestId("overview-worst-game")).toHaveText("Taidi");

    await alice.getByTestId("stats-tab-taidi").click();
    await expect(alice.getByTestId("taidi-total")).toHaveText("$0.60");
    await expect(alice.getByTestId("taidi-round-win-rate")).toHaveText("100%");
    await expect(alice.getByTestId("taidi-profit-rate")).toHaveText("100%");
    // Alice never lost a round, so there's nothing to take a rate of.
    await expect(alice.getByTestId("taidi-double-rate")).toHaveText("—");

    await alice.getByTestId("stats-tab-mahjong").click();
    await expect(alice.getByTestId("mahjong-total")).toHaveText("$2.00");
    await expect(alice.getByTestId("mahjong-hu-rate")).toHaveText("100%");
    await expect(alice.getByTestId("mahjong-zimo-rate")).toHaveText("0%");

    // A session bar opens that game's room, straight onto the right screen.
    await alice.getByTestId("stats-tab-overview").click();
    await alice.locator('[data-testid="chart-sessions"] svg g rect').first().click();
    await expect(alice).toHaveURL(/\/room\/[^?]+\?g=(taidi|mahjong)/);
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    // --- Bob's perspective: both games are losses.
    await bob.goto("/stats");
    await expect(bob.getByTestId("overview-total")).toHaveText("-$2.60", { timeout: 10_000 });
    await bob.getByTestId("stats-tab-taidi").click();
    await expect(bob.getByTestId("taidi-round-win-rate")).toHaveText("0%");
    // One losing round, at 1 card: paid, but not doubled.
    await expect(bob.getByTestId("taidi-double-rate")).toHaveText("0%");
  } finally {
    await close();
  }
});
