import { expect, test, type Page } from "@playwright/test";
import { randomBytes } from "node:crypto";
import { CONSOLE, PREFIX, signIn, state } from "../support/iden";

async function asAdmin(page: Page) {
  await signIn(page, state.admin.email, state.admin.password);
  await page.waitForURL(`${CONSOLE}/**`);
}

/** The value inside a "Shown once" panel, found by the panel's label. */
function shownOnce(page: Page, label: string) {
  return page.locator("p", { hasText: label }).locator("xpath=../..").locator("code");
}

async function next(page: Page, times = 1) {
  for (let i = 0; i < times; i++) await page.getByRole("button", { name: "Continue" }).click();
}

test.describe("administration", () => {
  /** D6 — Creating a user without a password shows the generated password once; it is not shown again after a reload or on the user's page. */
  test("D6 admin creates a user and the generated password is shown once", async ({ page }) => {
    test.info().annotations.push({
      type: "expected",
      description: "one-time password visible once, gone after reload",
    });
    const name = `${PREFIX}ui-${randomBytes(3).toString("hex")}`;
    await asAdmin(page);

    await page.goto(`${CONSOLE}/admin/users/new`);
    await page.getByLabel("Email").fill(name);
    await page.getByLabel("Username").fill(name);
    await page.getByLabel("Display name").fill("E2E Created By UI");
    await next(page, 3);
    await page.getByRole("button", { name: "Add user" }).click();

    const secret = shownOnce(page, "One-time password");
    await expect(secret).toBeVisible();
    const password = ((await secret.textContent()) ?? "").trim();
    expect(password.length).toBeGreaterThanOrEqual(12);

    await page.reload();
    await expect(page.getByText(password)).toHaveCount(0);
    await page.goto(`${CONSOLE}/admin/users`);
    await page
      .getByRole("row", { name: new RegExp(name) })
      .first()
      .click();
    await expect(page.getByText(name).first()).toBeVisible();
    await expect(page.getByText(password)).toHaveCount(0);
  });

  /** D7 — Registering a confidential (web) client shows its secret once; after a reload the secret is nowhere on the page or the client's record. */
  test("D7 admin registers a confidential client and the secret is shown once", async ({
    page,
  }) => {
    test.info().annotations.push({
      type: "expected",
      description: "client secret visible once, gone after reload",
    });
    const clientId = `${PREFIX}web-${randomBytes(3).toString("hex")}`;
    await asAdmin(page);

    await page.goto(`${CONSOLE}/admin/clients/new`);
    await page.getByLabel("Name").fill(`E2E Web ${clientId}`);
    await page.getByLabel("Client ID").fill(clientId);
    await next(page);
    await page
      .getByRole("textbox", { name: /^Redirect URIs/ })
      .fill("https://e2e.example.org/callback");
    await next(page, 3);
    await page.getByRole("button", { name: "Register client" }).click();

    const secret = shownOnce(page, "Client secret");
    await expect(secret).toBeVisible();
    const value = ((await secret.textContent()) ?? "").trim();
    expect(value.length).toBeGreaterThanOrEqual(32);

    await page.reload();
    await expect(page.getByText(value)).toHaveCount(0);
    await page.goto(`${CONSOLE}/admin/clients`);
    await page
      .getByRole("row", { name: new RegExp(clientId) })
      .first()
      .click();
    await expect(page.getByText(clientId).first()).toBeVisible();
    await expect(page.getByText(value)).toHaveCount(0);
  });
});
