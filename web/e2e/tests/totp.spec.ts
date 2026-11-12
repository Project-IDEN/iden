import { expect, test } from "@playwright/test";
import { authenticator } from "otplib";
import { CONSOLE, expectSignedInAs, signIn, signOut, state } from "../support/iden";

/** D3 — After enrolling an authenticator on the Security page, the next sign-in asks for a TOTP code and succeeds with it. */
test("D3 enrol TOTP, then sign in with password + TOTP", async ({ page }) => {
  test.info().annotations.push({
    type: "expected",
    description: "password then TOTP code reaches the dashboard",
  });
  const account = state.totp;

  await signIn(page, account.email, account.password);
  await expectSignedInAs(page, account.displayName);

  await page.goto(`${CONSOLE}/account/security`);
  await page.getByRole("button", { name: "Set up" }).click();
  const key = page
    .locator("p", { hasText: "Or enter this key by hand" })
    .locator("xpath=../..")
    .locator("code");
  const secret = ((await key.textContent()) ?? "").replace(/\s+/g, "");
  expect(secret).toMatch(/^[A-Z2-7]{16,}$/);
  const confirmingCode = authenticator.generate(secret);
  await page.getByLabel("Six-digit code").fill(confirmingCode);
  await page.getByRole("button", { name: "Turn on" }).click();
  await expect(page.getByText("On", { exact: true })).toBeVisible();

  await signOut(page);
  await signIn(page, account.email, account.password);
  await expect(page.getByRole("heading", { name: "Enter your code" })).toBeVisible();
  // The code that turned the authenticator on is spent; a person would wait for the next.
  await expect
    .poll(() => authenticator.generate(secret), { timeout: 35_000 })
    .not.toBe(confirmingCode);
  await page.getByLabel("Six-digit code").fill(authenticator.generate(secret));
  await page.getByRole("button", { name: "Continue" }).click();

  await expectSignedInAs(page, account.displayName);
});
