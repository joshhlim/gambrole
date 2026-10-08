import { deflateSync } from "node:zlib";
import { test, expect, type Page } from "@playwright/test";
import { amountFor, joinByCode, login, openNewRoom, players, submitNewRoom } from "./helpers";

// A real PNG built in memory (8x8, one colour), so the upload goes through
// the same decode-crop-encode path a photo from the camera roll would.
function crc32(buf: Buffer): number {
  let c = ~0;
  for (const byte of buf) {
    c ^= byte;
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  return ~c >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function solidPng(size = 8, rgb: [number, number, number] = [200, 60, 80]): Buffer {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // truecolour
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array(size).fill(rgb).flat())]);
  const raw = Buffer.concat(Array(size).fill(row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** The signed-in account's handle, once the top bar has loaded it. */
async function usernameOf(page: Page): Promise<string> {
  const name = page.getByTestId("account-name");
  await expect(name).toHaveText(/^@/, { timeout: 10_000 });
  return (await name.textContent())!.trim().slice(1);
}

test("settings: photo, about, accent, theme, currency and privacy", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Alice", "Bob"]);
  const [alice, bob] = pages;
  try {
    const handle = await usernameOf(alice);
    await alice.goto("/settings");

    // Photo: picked, squared and shrunk in the browser, then shown on the
    // settings card and in the top bar.
    await alice.getByTestId("avatar-file-input").setInputFiles({
      name: "me.png",
      mimeType: "image/png",
      buffer: solidPng(),
    });
    await expect(alice.getByTestId("avatar-status")).toHaveText("Saved.", { timeout: 10_000 });
    await expect(alice.getByTestId("account-btn").getByTestId("avatar-photo")).toBeVisible();

    await alice.getByTestId("settings-bio-input").fill("Plays every Friday.");
    await alice.getByTestId("settings-city-input").fill("Singapore");
    await alice.getByTestId("settings-save-about-btn").click();
    await expect(alice.getByTestId("settings-about-status")).toHaveText("Saved.");

    await alice.getByTestId("accent-ruby").click();
    await expect(alice.getByTestId("accent-ruby")).toHaveAttribute("aria-checked", "true");
    await expect(alice.getByTestId("settings-accent-status")).toHaveText("Saved.");

    // Dark: applied at once, and still dark after a reload (painted from
    // the device's cache before the account even loads).
    await alice.getByTestId("theme-dark").click();
    await expect(alice.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(alice.getByTestId("settings-theme-status")).toHaveText("Saved.");
    await alice.reload();
    await expect(alice.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(alice.getByTestId("theme-dark")).toHaveAttribute("aria-checked", "true", {
      timeout: 10_000,
    });

    await alice.getByTestId("settings-currency-select").selectOption("S$");
    await expect(alice.getByTestId("settings-currency-status")).toHaveText("Saved.");

    // Bob sees what Alice shares.
    await bob.goto(`/u/${handle}`);
    await expect(bob.getByTestId("profile-bio")).toHaveText("Plays every Friday.", { timeout: 10_000 });
    await expect(bob.getByTestId("profile-city")).toHaveText("Singapore");
    await expect(bob.getByTestId("avatar-photo")).toBeVisible();

    // A quick game: every amount Alice sees uses her symbol; Bob's don't.
    await openNewRoom(alice, "taidi");
    const code = await submitNewRoom(alice);
    await joinByCode(bob, code);
    await expect(alice.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });
    await alice.getByTestId("start-game-btn").click();
    await expect(alice.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await alice.getByTestId("win-btn").click();
    await expect(bob.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    await bob.getByTestId("cards-input").fill("1");
    await bob.getByTestId("submit-cards-btn").click();
    await expect(amountFor(alice, "Alice-")).toHaveText("S$0.60", { timeout: 10_000 });
    await expect(amountFor(bob, "Alice-")).toHaveText("$0.60", { timeout: 10_000 });
    await alice.getByTestId("end-game-btn").click();
    await alice.getByTestId("confirm-end-btn").click();
    await expect(alice.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });
    await alice.goto("/debts");
    await alice.getByTestId("debts-tab-owed").click();
    await expect(alice.getByText("S$0.60")).toBeVisible({ timeout: 10_000 });

    // Hiding bio and city: Bob's view of the page just leaves them out.
    await alice.goto("/settings");
    await alice.getByTestId("profile-visibility-nobody").click();
    await expect(alice.getByTestId("settings-privacy-status")).toHaveText("Saved.");
    await bob.goto(`/u/${handle}`);
    await expect(bob.getByTestId("profile-name")).toBeVisible({ timeout: 10_000 });
    await expect(bob.getByTestId("profile-bio")).toHaveCount(0);
    await expect(bob.getByTestId("profile-city")).toHaveCount(0);
  } finally {
    await close();
  }
});

test("a Taidi rule set saved as the default is where /new starts", async ({ page }) => {
  await login(page, `Defaults-${Date.now().toString(36)}`);
  await openNewRoom(page, "taidi");
  await page.getByTestId("rule-card-value").fill("0.50");
  await page.getByTestId("save-default-taidi").click();
  await expect(page.getByTestId("save-default-note")).toHaveText("Saved as your default.");

  await page.reload();
  await page.getByTestId("game-tile-taidi").click();
  await expect(page.getByTestId("rule-card-value")).toHaveValue("0.50", { timeout: 10_000 });

  // Settings shows it, and clearing it puts /new back on the standard rules.
  await page.goto("/settings");
  await expect(page.getByTestId("default-rules-taidi-summary")).toContainText("$0.50/card");
  await page.getByTestId("default-rules-taidi-clear").click();
  await expect(page.getByTestId("default-rules-taidi-summary")).toHaveText("Not set");
  await page.goto("/new");
  await page.getByTestId("game-tile-taidi").click();
  await expect(page.getByTestId("rule-card-value")).toHaveValue("0.20");
});

test("a new account sees the walkthrough once; skipping it is for good", async ({ page }) => {
  await login(page, `Newbie-${Date.now().toString(36)}`, { keepOnboarding: true });
  const overlay = page.getByTestId("onboarding");
  await expect(overlay).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("onboarding-step")).toHaveAttribute("data-step", "0");
  await page.getByTestId("onboarding-next").click();
  await expect(page.getByTestId("onboarding-step")).toHaveAttribute("data-step", "1");

  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/users/me/preferences") && r.ok()),
    page.getByTestId("onboarding-skip").click(),
  ]);
  await expect(overlay).toBeHidden();

  await page.reload();
  await usernameOf(page);
  await expect(page.getByTestId("play-btn")).toBeVisible();
  // Give it every chance to wrongly reappear: the history check that would
  // open it runs right after the profile loads.
  await page.waitForTimeout(1500);
  await expect(overlay).toHaveCount(0);
});

test("a friend request from a profile page, accepted from the other's", async ({ browser }) => {
  const { pages, close } = await players(browser, ["Ann", "Ben"]);
  const [ann, ben] = pages;
  try {
    const annHandle = await usernameOf(ann);
    const benHandle = await usernameOf(ben);

    await ann.goto(`/u/${benHandle}`);
    await expect(ann.getByTestId("profile-username")).toHaveText(`@${benHandle}`, { timeout: 10_000 });
    await ann.getByTestId("profile-add-btn").click();
    await expect(ann.getByTestId("profile-friend-state")).toHaveText("Requested");

    await ben.goto(`/u/${annHandle}`);
    await ben.getByTestId("profile-accept-btn").click();
    await expect(ben.getByTestId("profile-friend-state")).toHaveText("Friends");
    // Friends see each other's headline stats.
    await expect(ben.getByTestId("profile-stat-games")).toHaveText("0");

    await ann.reload();
    await expect(ann.getByTestId("profile-friend-state")).toHaveText("Friends", { timeout: 10_000 });

    // Stats kept private: the stats page says so instead of erroring.
    await ben.goto("/settings");
    await ben.getByTestId("stats-visibility-nobody").click();
    await expect(ben.getByTestId("settings-privacy-status")).toHaveText("Saved.");
    await ann.reload();
    await expect(ann.getByTestId("profile-friend-state")).toHaveText("Friends", { timeout: 10_000 });
    await expect(ann.getByTestId("profile-stat-games")).toHaveCount(0);
    await ann.goto("/friends");
    await ann.locator('[data-testid^="friend-stats-"]').click();
    await expect(ann.getByTestId("stats-private")).toHaveText("These stats are private.", {
      timeout: 10_000,
    });
  } finally {
    await close();
  }
});
