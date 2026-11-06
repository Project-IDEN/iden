import { createServer, type Server } from "node:http";
import { expect, test } from "@playwright/test";
import { AUTH_UI, ISSUER, THIRD_PARTY_REDIRECT, pkce, state } from "../support/iden";

function authorizeUrl(extra: Record<string, string> = {}) {
  const url = new URL(`${ISSUER}/oauth2/authorize`);
  url.search = new URLSearchParams({
    client_id: state.thirdParty.clientId,
    redirect_uri: THIRD_PARTY_REDIRECT,
    response_type: "code",
    scope: "openid profile",
    state: "e2e-consent",
    code_challenge: pkce().challenge,
    code_challenge_method: "S256",
    ...extra,
  }).toString();
  return url.toString();
}

/**
 * The third party itself: a page on its redirect URI, so the browser has somewhere
 * to land. Not `page.route` — Playwright does not route a request reached by
 * following a redirect, which is exactly how the result of consent arrives.
 */
let thirdParty: Server;
test.beforeAll(async () => {
  const { hostname, port } = new URL(THIRD_PARTY_REDIRECT);
  thirdParty = createServer((_, response) => response.end("third party"));
  await new Promise<void>((resolve) => thirdParty.listen(Number(port), hostname, resolve));
});
test.afterAll(() => new Promise<void>((resolve) => thirdParty.close(() => resolve())));

/** D4 — Approving the consent screen returns to the client with a code; denying it returns access_denied. */
test("D4 third-party consent: approve gives a code, deny gives access_denied", async ({ page }) => {
  test.info().annotations.push({
    type: "expected",
    description: "approve -> ?code=…, deny -> ?error=access_denied",
  });
  await page.goto(authorizeUrl());
  await page.waitForURL(`${AUTH_UI}/auth/login**`);
  await page.getByLabel("Email").fill(state.consent.email);
  await page.getByLabel("Password").fill(state.consent.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.waitForURL(`${AUTH_UI}/auth/consent**`);
  await expect(page.getByRole("heading", { name: "Allow access?" })).toBeVisible();
  await page.getByRole("button", { name: "Allow access" }).click();
  await page.waitForURL(`${THIRD_PARTY_REDIRECT}**`);
  const approved = new URL(page.url()).searchParams;
  expect(approved.get("code")).toBeTruthy();
  expect(approved.get("state")).toBe("e2e-consent");
  expect(approved.get("iss")).toBe(ISSUER);

  // Already consented, so ask again explicitly for the denial.
  await page.goto(authorizeUrl({ prompt: "consent" }));
  await page.waitForURL(`${AUTH_UI}/auth/consent**`);
  await page.getByRole("button", { name: "Deny" }).click();
  await page.waitForURL(`${THIRD_PARTY_REDIRECT}**`);
  const denied = new URL(page.url()).searchParams;
  expect(denied.get("error")).toBe("access_denied");
  expect(denied.get("code")).toBeNull();
});
