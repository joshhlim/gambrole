import { expect, test } from "@playwright/test";
import { login, openNewRoom, submitNewRoom } from "./helpers";

test("deleting your account: refused mid-game, then gone for good", async ({ page }) => {
  await login(page, `Leaver-${Date.now().toString(36)}`);

  // In a lobby, the API refuses and Settings says why.
  await openNewRoom(page, "taidi");
  await submitNewRoom(page);
  await page.goto("/settings");
  await page.getByTestId("settings-delete-account-btn").click();
  await page.getByTestId("settings-delete-account-confirm").click();
  await expect(page.getByTestId("settings-delete-account-error")).toContainText("current game");

  // Out of the game, it goes through and lands signed out.
  await page.goto("/");
  await page.getByTestId("rejoin-room-btn").click();
  await page.getByTestId("disband-room-btn").click();
  await page.getByTestId("confirm-disband-btn").click();
  await expect(page).toHaveURL("/");

  await page.goto("/settings");
  await page.getByTestId("settings-delete-account-btn").click();
  await page.getByTestId("settings-delete-account-confirm").click();
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("display-name-input")).toBeVisible();
  await expect(page.getByTestId("tab-bar")).toHaveCount(0);
});
