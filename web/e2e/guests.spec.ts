import { test, expect, type Page } from "@playwright/test";
import { amountFor, openNewRoom, players, submitNewRoom } from "./helpers";

/**
 * One phone running the table: the host seats a guest with no account,
 * enters the guest's turns, and the guest claims the game afterwards.
 */

async function addGuest(page: Page, name: string, total: number) {
  await page.getByTestId("guest-name-input").fill(name);
  await page.getByTestId("add-guest-btn").click();
  await expect(page.getByTestId("lobby-member")).toHaveCount(total, { timeout: 10_000 });
}

const actAs = (page: Page, name: string) =>
  page.getByTestId("acting-as-option").filter({ hasText: name }).click();

test("a host plays a Taidi game for a guest, who claims it afterwards", async ({ browser }) => {
  const uniq = Date.now().toString(36);
  const gus = `Gus-${uniq}`;
  const { pages, close } = await players(browser, ["Host"]);
  const [host] = pages;
  const claimerCtx = await browser.newContext();

  try {
    await openNewRoom(host, "taidi");
    await submitNewRoom(host);
    const roomId = new URL(host.url()).pathname.split("/").pop()!;

    // Names are unique at the table, case-insensitively.
    await addGuest(host, gus, 2);
    await expect(host.getByTestId("guest-tag")).toHaveCount(1);
    await host.getByTestId("guest-name-input").fill(gus.toUpperCase());
    await host.getByTestId("add-guest-btn").click();
    await expect(host.getByTestId("room-banner")).toContainText("already at the table");
    await expect(host.getByTestId("lobby-member")).toHaveCount(2);

    await host.getByTestId("start-game-btn").click();
    await expect(host.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });

    // Round 1: the guest wins. Defaults are 20c/card, base 2, so the host's
    // 3 cards cost (3 + 2) x 20c = $1.00.
    await actAs(host, gus);
    await expect(host.getByTestId("win-btn")).toHaveText(`Win · ${gus}`);
    await host.getByTestId("win-btn").click();
    await host.getByTestId("cards-input").fill("3");
    await host.getByTestId("submit-cards-btn").click();
    await expect(amountFor(host, gus)).toHaveText("$1.00", { timeout: 10_000 });

    // The picker went back to the host: round 2 is the host's own win, and
    // the guest's count is entered from the host's phone ((5 + 2) x 20c).
    await expect(host.getByTestId("win-btn")).toHaveText("Win");
    await host.getByTestId("win-btn").click();
    const row = host.locator(`[data-testid="guest-cards-row"][data-player="${gus}"]`);
    await row.getByTestId("guest-cards-input").fill("5");
    await row.getByTestId("guest-cards-submit").click();
    await expect(amountFor(host, gus)).toHaveText("-$0.40", { timeout: 10_000 });
    await expect(amountFor(host, "Host-")).toHaveText("$0.40");

    await host.getByTestId("end-game-btn").click();
    await host.getByTestId("confirm-end-btn").click();
    await expect(host.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    const share = host.locator(`[data-testid="guest-link-row"][data-player="${gus}"]`).getByTestId("guest-share-btn");
    const claimLink = new URL((await share.getAttribute("data-url"))!);
    expect(claimLink.pathname).toMatch(/^\/claim\/.+/);

    // The guest, on their own phone with no account yet.
    const claimer = await claimerCtx.newPage();
    await claimer.goto(claimLink.pathname);
    await expect(claimer.getByTestId("claim-name")).toHaveText(gus);
    await expect(claimer.getByTestId("claim-net")).toHaveText("-$0.40");
    await claimer.getByTestId("display-name-input").fill(`Claimer-${uniq}`);
    await claimer.getByTestId("continue-btn").click();
    await claimer.getByTestId("claim-btn").click();
    await expect(claimer).toHaveURL(new RegExp(`/room/${roomId}`), { timeout: 10_000 });
    await expect(claimer.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    await claimer.goto("/history");
    await expect(claimer.getByTestId(`history-row-${roomId}`)).toBeVisible({ timeout: 10_000 });

    // The link is spent.
    await claimer.goto(claimLink.pathname);
    await expect(claimer.getByTestId("claim-status")).toHaveText("Already claimed.");
    await host.reload();
    await expect(
      host.locator(`[data-testid="guest-link-row"][data-player="${gus}"]`).getByTestId("guest-claimed"),
    ).toBeVisible({ timeout: 10_000 });
  } finally {
    await claimerCtx.close();
    await close();
  }
});

test("a debt with an unclaimed guest is settled by one side", async ({ browser }) => {
  const gus = `Gus-${Date.now().toString(36)}`;
  const { pages, close } = await players(browser, ["Debtor"]);
  const [host] = pages;

  try {
    await openNewRoom(host, "taidi");
    await submitNewRoom(host);
    await addGuest(host, gus, 2);
    await host.getByTestId("start-game-btn").click();

    await actAs(host, gus);
    await host.getByTestId("win-btn").click();
    await host.getByTestId("cards-input").fill("1");
    await host.getByTestId("submit-cards-btn").click();
    await expect(amountFor(host, gus)).toHaveText("$0.60", { timeout: 10_000 });
    await host.getByTestId("end-game-btn").click();
    await host.getByTestId("confirm-end-btn").click();
    await expect(host.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    await host.goto("/debts");
    const debt = host.locator('[data-testid^="debt-owing-"]').filter({ hasText: gus });
    await expect(debt.getByTestId("guest-tag")).toBeVisible({ timeout: 10_000 });
    // No two-step for a guest: one tap closes it.
    await expect(debt.locator('[data-testid^="mark-paid-btn-"]')).toHaveCount(0);
    await debt.locator('[data-testid^="settle-btn-"]').click();
    await expect(debt).toContainText("Settled", { timeout: 10_000 });
  } finally {
    await close();
  }
});

test("guests fill a Mahjong table and the host declares for one", async ({ browser }) => {
  const uniq = Date.now().toString(36);
  const [g1, g2, g3] = ["Ann", "Ben", "Cy"].map((n) => `${n}-${uniq}`);
  const { pages, close } = await players(browser, ["MjHost"]);
  const [host] = pages;

  try {
    await openNewRoom(host, "mahjong");
    await submitNewRoom(host);
    await addGuest(host, g1, 2);
    await addGuest(host, g2, 3);
    await addGuest(host, g3, 4);
    // A full table: no more guests.
    await expect(host.getByTestId("guest-name-input")).toHaveCount(0);

    // Seat swaps work with guests: the host (seat 0) trades with g3 (seat 3).
    const seatOf = (name: string) =>
      host.locator(`[data-testid="lobby-member"][data-player^="${name}"]`);
    await seatOf("MjHost").click();
    await seatOf(g3).click();
    await expect(seatOf(g3)).toHaveAttribute("data-seat", "0", { timeout: 10_000 });
    await expect(seatOf("MjHost")).toHaveAttribute("data-seat", "3");

    // Removing and re-adding a guest frees and refills a seat.
    await host
      .locator(`[data-testid="lobby-member"][data-player="${g2}"]`)
      .locator("..")
      .getByTestId("remove-guest-btn")
      .click();
    await expect(host.getByTestId("lobby-member")).toHaveCount(3, { timeout: 10_000 });
    await addGuest(host, g2, 4);

    await host.getByTestId("start-game-btn").click();
    await expect(host.getByTestId("yao-btn")).toBeVisible({ timeout: 10_000 });

    // g1 bites the host (seat 3): the host alone pays yao = $1.00.
    await actAs(host, g1);
    await host.getByTestId("yao-btn").click();
    await expect(host.getByTestId("flow-actor")).toHaveText(`For ${g1}`);
    await host.getByTestId("pick-seat-3").click();
    await host.getByTestId("yao-ming-btn").click();
    await expect(amountFor(host, g1)).toHaveText("$1.00", { timeout: 10_000 });
    await expect(amountFor(host, "MjHost")).toHaveText("-$1.00");

    // Back to acting as the host.
    await expect(host.getByTestId("acting-as-option").filter({ hasText: "You" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  } finally {
    await close();
  }
});
