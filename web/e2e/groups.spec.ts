import { test, expect } from "@playwright/test";
import { amountFor, joinByCode, players, skipOnboarding, submitNewRoom } from "./helpers";

test("a group: create, join by link, play a game in it, rotate the code", async ({ browser }) => {
  const uniq = Date.now().toString(36);
  const groupName = `Crew ${uniq}`;
  const { pages, close } = await players(browser, ["Owner"]);
  const [owner] = pages;
  const friendCtx = await browser.newContext();

  try {
    await owner.goto("/");
    await owner.getByTestId("groups-btn").click();
    await owner.getByTestId("group-name-input").fill(groupName);
    await owner.getByTestId("create-group-btn").click();
    await expect(owner.getByTestId("group-title")).toHaveText(groupName, { timeout: 10_000 });
    const groupId = new URL(owner.url()).pathname.split("/").pop()!;

    await owner.getByTestId("group-tab-members").click();
    const oldCode = (await owner.getByTestId("group-invite-code").textContent())!.trim();
    const link = new URL((await owner.getByTestId("group-share-btn").getAttribute("data-url"))!);
    expect(link.pathname).toBe(`/groups/join/${oldCode}`);

    // A friend opens the link signed out, signs in, and lands in the group.
    const friend = await friendCtx.newPage();
    await friend.goto(link.pathname);
    await friend.getByTestId("display-name-input").fill(`Friend-${uniq}`);
    await friend.getByTestId("continue-btn").click();
    await expect(friend).toHaveURL(new RegExp(`/groups/${groupId}`), { timeout: 10_000 });
    await expect(friend.getByTestId("group-title")).toHaveText(groupName);
    await skipOnboarding(friend);

    // "New game" from the group arrives on /new with it preselected.
    await owner.getByTestId("group-new-game-btn").click();
    await expect(owner.getByTestId("group-select")).toHaveValue(groupId, { timeout: 10_000 });
    await owner.getByTestId("game-tile-taidi").click();
    const code = await submitNewRoom(owner);
    await expect(owner.getByTestId("room-group-name")).toHaveText(groupName, { timeout: 10_000 });

    await joinByCode(friend, code);
    await expect(owner.getByTestId("lobby-member")).toHaveCount(2, { timeout: 10_000 });
    await owner.getByTestId("start-game-btn").click();
    await expect(owner.getByTestId("win-btn")).toBeVisible({ timeout: 10_000 });
    await owner.getByTestId("win-btn").click();
    await expect(friend.getByTestId("cards-input")).toBeVisible({ timeout: 10_000 });
    await friend.getByTestId("cards-input").fill("1");
    await friend.getByTestId("submit-cards-btn").click();
    await expect(amountFor(owner, "Owner-")).toHaveText("$0.60", { timeout: 10_000 });
    await owner.getByTestId("end-game-btn").click();
    await owner.getByTestId("confirm-end-btn").click();
    await expect(owner.getByTestId("game-over")).toBeVisible({ timeout: 10_000 });

    // Both on the leaderboard, best first.
    for (const p of [owner, friend]) {
      await p.goto(`/groups/${groupId}`);
      const rows = p.getByTestId("leaderboard-row");
      await expect(rows).toHaveCount(2, { timeout: 10_000 });
      await expect(rows.first()).toHaveAttribute("data-player", /^Owner-/);
      await expect(rows.first().getByTestId("leaderboard-net")).toHaveText("$0.60");
      await expect(rows.nth(1).getByTestId("leaderboard-net")).toHaveText("-$0.60");
    }
    await owner.getByTestId("group-tab-games").click();
    await expect(owner.getByTestId("group-game-row")).toHaveCount(1);

    // A new code kills the old link.
    await owner.getByTestId("group-tab-members").click();
    await owner.getByTestId("rotate-code-btn").click();
    await owner.getByTestId("confirm-rotate-code-btn").click();
    await expect(owner.getByTestId("group-invite-code")).not.toHaveText(oldCode, { timeout: 10_000 });
    await friend.goto(link.pathname);
    await expect(friend.getByTestId("group-join-error")).toBeVisible({ timeout: 10_000 });
  } finally {
    await friendCtx.close();
    await close();
  }
});
