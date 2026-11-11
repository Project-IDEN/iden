import { expect, test } from "@playwright/test";
import { CONSOLE, expectSignedInAs, signIn, silentAuthorize, state } from "../support/iden";

/** D8 — Revoking another browser's session on the Sessions page ends it: that browser's next request to the provider gets login_required. */
test("D8 revoking another session ends it", async ({ browser }) => {
  test.info().annotations.push({
    type: "expected",
    description: "revoked browser's next authorize -> login_required",
  });
  const account = state.sessions;
  const mine = await browser.newContext();
  const other = await browser.newContext();
  const page = await mine.newPage();
  const otherPage = await other.newPage();

  await signIn(otherPage, account.email, account.password);
  await expectSignedInAs(otherPage, account.displayName);
  expect((await silentAuthorize(other.request)).get("code")).toBeTruthy();

  await signIn(page, account.email, account.password);
  await expectSignedInAs(page, account.displayName);
  await page.goto(`${CONSOLE}/account/sessions`);
  // Two rows: this browser (badged "this device", its Revoke disabled) and the other one.
  const sessions = page
    .getByRole("listitem")
    .filter({ has: page.getByRole("button", { name: "Revoke" }) });
  await expect(sessions).toHaveCount(2);
  const otherRow = sessions.filter({ hasNotText: "this device" });
  await otherRow.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("button", { name: "Sign it out" }).click();
  await expect(sessions).toHaveCount(1);

  const after = await silentAuthorize(other.request);
  expect(after.get("error")).toBe("login_required");
  expect(after.get("code")).toBeNull();

  await mine.close();
  await other.close();
});
