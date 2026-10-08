import { expect, type Browser, type Page } from "@playwright/test";

/** Dev-mode sign-in. Home has no "signed in as" line any more; the Play
 * button is what only a signed-in home shows. Every name here is new, so
 * the first-run walkthrough always opens — and is skipped, since it covers
 * home. Pass `keepOnboarding` to look at it instead. */
export async function login(page: Page, name: string, opts: { keepOnboarding?: boolean } = {}) {
  await page.goto("/");
  await page.getByTestId("display-name-input").fill(name);
  await page.getByTestId("continue-btn").click();
  await expect(page.getByTestId("play-btn")).toBeVisible();
  if (!opts.keepOnboarding) await skipOnboarding(page);
}

/** For a new account signed in some other way (a shared link's sign-in):
 * the walkthrough opens on home, so go there and skip it. */
export async function skipOnboarding(page: Page) {
  if (new URL(page.url()).pathname !== "/") await page.goto("/");
  await page.getByTestId("onboarding-skip").click({ timeout: 15_000 });
  await expect(page.getByTestId("onboarding")).toBeHidden();
}

/** Home → Play → Create → the game's rules form. */
export async function openNewRoom(page: Page, game: "taidi" | "mahjong" | "poker") {
  await page.goto("/");
  await page.getByTestId("play-btn").click();
  await page.getByTestId("create-room-option").click();
  await expect(page).toHaveURL(/\/new/);
  await page.getByTestId(`game-tile-${game}`).click();
}

/** Submits the open rules form and returns the new room's invite code. */
export async function submitNewRoom(page: Page): Promise<string> {
  await page.getByTestId("create-room-btn").click();
  await expect(page).toHaveURL(/\/room\//);
  const code = (await page.getByTestId("invite-code").textContent())?.trim() ?? "";
  expect(code).toMatch(/^[A-Z0-9]{6}$/);
  return code;
}

/** Home → Play → Join → code. */
export async function joinByCode(page: Page, code: string) {
  await page.goto("/");
  await page.getByTestId("play-btn").click();
  await page.getByTestId("join-room-option").click();
  await page.getByTestId("room-code-input").fill(code);
  await page.getByTestId("join-room-btn").click();
  await expect(page).toHaveURL(/\/room\//);
}

export function amountFor(page: Page, namePrefix: string) {
  return page
    .locator(
      `[data-testid="standing-row"][data-player^="${namePrefix}"] [data-testid="standing-amount"]`,
    )
    .first();
}

/** N signed-in players, each in their own browser context (= device). */
export async function players(browser: Browser, names: string[]) {
  const uniq = Date.now().toString(36);
  const contexts = await Promise.all(names.map(() => browser.newContext()));
  const pages = await Promise.all(contexts.map((c) => c.newPage()));
  await Promise.all(pages.map((p, i) => login(p, `${names[i]}-${uniq}`)));
  return {
    pages,
    close: () => Promise.all(contexts.map((c) => c.close())),
  };
}
