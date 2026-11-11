import { expect, test, type Page } from "@playwright/test";
import { AUTH_UI, CONSOLE, state } from "../support/iden";

async function askForReset(page: Page, email: string) {
  await page.goto(`${CONSOLE}/`);
  await page.waitForURL(`${AUTH_UI}/auth/login**`);
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  return (await page.getByText(/belongs to an account/).innerText()).replace(email, "<email>");
}

/** D9 — Asking for a reset with a known and with an unknown address shows the identical response, so it cannot reveal who has an account. */
test("D9 forgot password answers known and unknown addresses identically", async ({ page }) => {
  test
    .info()
    .annotations.push({ type: "expected", description: "same page text (address aside) for both" });
  const known = await askForReset(page, state.member.email);
  const unknown = await askForReset(page, `nobody-${Date.now()}@localhost`);

  expect(unknown).toBe(known);
});
