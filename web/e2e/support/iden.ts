/**
 * What the E2E suite needs to know about the local stack, and the admin-API
 * helpers its setup and teardown use.
 *
 * Local only: every URL defaults to the docker compose ports on this machine.
 */
import { createHash, randomBytes } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const ISSUER = process.env.E2E_ISSUER ?? "http://localhost:8000";
export const AUTH_UI = process.env.E2E_AUTH_UI ?? "http://localhost:4000";
export const DASHBOARD = process.env.E2E_DASHBOARD ?? "http://localhost:3000";
export const CONSOLE = `${DASHBOARD}/console`;
const DASHBOARD_CALLBACK = `${CONSOLE}/callback`;

/** Where a third-party test client is sent back to. Nothing listens there; the tests intercept it. */
export const THIRD_PARTY_REDIRECT = "http://127.0.0.1:5999/callback";

/** Every account and client the suite creates starts with this, so teardown can find them. */
export const PREFIX = "e2e-";

const STATE_FILE = fileURLToPath(new URL("../.state.json", import.meta.url));

export interface Account {
  id: string;
  email: string;
  password: string;
  displayName: string;
}

export interface State {
  admin: { email: string; password: string };
  member: Account;
  totp: Account;
  sessions: Account;
  consent: Account;
  revoked: Account;
  thirdParty: { id: string; clientId: string };
}

export function adminCredentials() {
  const email = process.env.E2E_ADMIN_EMAIL ?? "admin@localhost";
  const password = process.env.E2E_ADMIN_PASSWORD;
  if (!password) {
    throw new Error(
      "Set E2E_ADMIN_PASSWORD to the seeded administrator's password (see web/e2e/README.md).",
    );
  }
  return { email, password };
}

export function saveState(state: State) {
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

export function loadState(): State {
  return JSON.parse(readFileSync(STATE_FILE, "utf8")) as State;
}

/**
 * What global setup created, read when a test first touches it — spec files
 * are loaded to list the tests before global setup has written the file.
 */
export const state: State = new Proxy({} as State, {
  get: (_, key) => loadState()[key as keyof State],
});

export function pkce() {
  const verifier = randomBytes(48).toString("base64url");
  const challenge = createHash("sha256").update(verifier).digest("base64url");
  return { verifier, challenge };
}

function cookieFrom(response: Response): string {
  const raw = response.headers.getSetCookie?.() ?? [];
  return raw.map((line) => line.split(";")[0]).join("; ");
}

/**
 * An access token for the administrator, by the same authorization-code + PKCE
 * round trip the dashboard makes — no shortcut around the provider.
 */
export async function adminToken(): Promise<string> {
  const { email, password } = adminCredentials();
  const discovery = (await (await fetch(`${ISSUER}/.well-known/openid-configuration`)).json()) as {
    scopes_supported: string[];
  };
  const { verifier, challenge } = pkce();
  const authorize = new URL(`${ISSUER}/oauth2/authorize`);
  authorize.search = new URLSearchParams({
    client_id: "dashboard",
    redirect_uri: DASHBOARD_CALLBACK,
    response_type: "code",
    scope: discovery.scopes_supported.join(" "),
    state: "e2e-setup",
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();

  const first = await fetch(authorize, { redirect: "manual" });
  const challengeId = new URL(first.headers.get("location") ?? "").searchParams.get("challenge");
  if (!challengeId) throw new Error(`authorize did not hand over to the Auth UI: ${first.status}`);

  const login = await fetch(`${ISSUER}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ challengeId, email, password }),
  });
  if (!login.ok) throw new Error(`admin sign-in failed: ${login.status} ${await login.text()}`);
  const step = (await login.json()) as { status: string; resumeUrl: string | null };
  if (step.status !== "complete" || !step.resumeUrl) {
    throw new Error(
      `admin sign-in needs another method (${step.status}); use an admin without TOTP`,
    );
  }

  const resumed = await fetch(step.resumeUrl, {
    redirect: "manual",
    headers: { cookie: cookieFrom(login) },
  });
  const code = new URL(resumed.headers.get("location") ?? "").searchParams.get("code");
  if (!code) throw new Error(`no code after sign-in: ${resumed.headers.get("location")}`);

  const token = await fetch(`${ISSUER}/oauth2/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: DASHBOARD_CALLBACK,
      code_verifier: verifier,
      client_id: "dashboard",
    }),
  });
  const body = (await token.json()) as { access_token?: string };
  if (!body.access_token) throw new Error(`token exchange failed: ${JSON.stringify(body)}`);
  return body.access_token;
}

export async function api<T>(token: string, method: string, path: string, body?: unknown) {
  const response = await fetch(`${ISSUER}${path}`, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} -> ${response.status} ${await response.text()}`);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/**
 * Sign in through the real pages: the dashboard sends the browser to
 * /oauth2/authorize, which hands it to the Auth UI.
 */
export async function signIn(page: Page, email: string, password: string) {
  await page.goto(`${CONSOLE}/`);
  await page.waitForURL(`${AUTH_UI}/auth/login**`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export async function expectSignedInAs(page: Page, name: string) {
  await page.waitForURL(`${CONSOLE}/**`);
  await expect(page.getByRole("button", { name: /Account menu/ })).toContainText(name);
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: /Account menu/ }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
}

/** What /oauth2/authorize says about this browser's session, without showing any page (prompt=none). */
export async function silentAuthorize(request: APIRequestContext) {
  const url = new URL(`${ISSUER}/oauth2/authorize`);
  url.search = new URLSearchParams({
    client_id: "dashboard",
    redirect_uri: `${CONSOLE}/callback`,
    response_type: "code",
    scope: "openid",
    state: "e2e-silent",
    code_challenge: pkce().challenge,
    code_challenge_method: "S256",
    prompt: "none",
  }).toString();
  const response = await request.get(url.toString(), { maxRedirects: 0 });
  return new URL(response.headers()["location"] ?? "").searchParams;
}
