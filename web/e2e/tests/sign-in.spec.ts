import { expect, test } from "@playwright/test";
import { AUTH_UI, CONSOLE, expectSignedInAs, signIn, signOut, state } from "../support/iden";

test.describe("password sign-in", () => {
  /** D1 — Signing in with the right password lands on the dashboard, which shows the person's display name. */
  test("D1 password sign-in shows the user's name", async ({ page }) => {
    test
      .info()
      .annotations.push({ type: "expected", description: "dashboard shows the display name" });
    await signIn(page, state.member.email, state.member.password);
    await expectSignedInAs(page, state.member.displayName);
  });

  /** D2 — A wrong password shows an error notice and the browser stays on the sign-in page. */
  test("D2 wrong password shows a notice and stays on sign-in", async ({ page }) => {
    test
      .info()
      .annotations.push({ type: "expected", description: "error notice, still on /auth/login" });
    await signIn(page, state.member.email, "definitely-not-the-password");

    await expect(page.getByText("That email and password don't match")).toBeVisible();
    expect(page.url()).toContain(`${AUTH_UI}/auth/login`);
  });

  /** D10 — Signing out clears the session, so opening a protected page sends the browser back to sign-in. */
  test("D10 sign out clears the session", async ({ page }) => {
    test.info().annotations.push({
      type: "expected",
      description: "protected page redirects to sign-in after sign-out",
    });
    await signIn(page, state.member.email, state.member.password);
    await expectSignedInAs(page, state.member.displayName);

    await signOut(page);
    await page.goto(`${CONSOLE}/account/profile`);

    await page.waitForURL(`${AUTH_UI}/auth/login**`);
    await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  });
});
