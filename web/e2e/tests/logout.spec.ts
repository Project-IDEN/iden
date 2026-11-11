import { expect, test } from "@playwright/test";
import { AUTH_UI, ISSUER, expectSignedInAs, signIn, silentAuthorize, state } from "../support/iden";

/** D12 — A logout link with no proof an application sent it (no id_token_hint) asks first: "Stay signed in" keeps the session, "Sign out" ends it. */
test("D12 a bare logout link asks before ending the session", async ({ page }) => {
  test.info().annotations.push({
    type: "expected",
    description: "asked on the sign-in page; stay -> still signed in; sign out -> login_required",
  });
  const account = state.member;
  await signIn(page, account.email, account.password);
  await expectSignedInAs(page, account.displayName);

  await page.goto(`${ISSUER}/oauth2/logout`);
  await page.waitForURL(`${AUTH_UI}/auth/logout**`);
  await page.getByRole("button", { name: "Stay signed in" }).click();
  await expect(page.getByRole("heading", { name: "You're still signed in" })).toBeVisible();
  expect((await silentAuthorize(page.request)).get("code")).toBeTruthy();

  await page.goto(`${ISSUER}/oauth2/logout`);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "You're signed out" })).toBeVisible();
  expect((await silentAuthorize(page.request)).get("error")).toBe("login_required");
});
