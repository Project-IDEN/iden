import { expect, test } from "@playwright/test";
import { CONSOLE, expectSignedInAs, signIn, state } from "../support/iden";

/** D5 — A member sees no admin pages in the navigation, and typing an admin URL directly shows "You don't have access to this". */
test("D5 a member cannot see or open admin pages", async ({ page }) => {
  test.info().annotations.push({
    type: "expected",
    description: "no Administration nav; direct URL blocked",
  });
  await signIn(page, state.member.email, state.member.password);
  await expectSignedInAs(page, state.member.displayName);

  const nav = page.getByRole("navigation");
  await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Clients" })).toHaveCount(0);

  for (const path of ["/admin/users", "/admin/clients/new", "/admin/audit"]) {
    await page.goto(`${CONSOLE}${path}`);
    await expect(page.getByText("You don't have access to this")).toBeVisible();
  }
});
