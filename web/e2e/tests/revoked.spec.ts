import { expect, test } from "@playwright/test";
import {
  AUTH_UI,
  CONSOLE,
  adminToken,
  api,
  expectSignedInAs,
  signIn,
  state,
} from "../support/iden";

/** D11 — When the provider stops accepting the dashboard's token, the next request sends the person to sign in rather than showing an error whose "Try again" can never succeed. */
test("D11 a token the provider refuses sends the dashboard back to sign-in", async ({ page }) => {
  test.info().annotations.push({
    type: "expected",
    description: "account deactivated while signed in -> next page lands on the sign-in page",
  });
  const account = state.revoked;
  await signIn(page, account.email, account.password);
  await expectSignedInAs(page, account.displayName);

  await api(await adminToken(), "PATCH", `/admin/users/${account.id}`, { isActive: false });
  await page.goto(`${CONSOLE}/account/sessions`);

  await page.waitForURL(`${AUTH_UI}/auth/login**`);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});
