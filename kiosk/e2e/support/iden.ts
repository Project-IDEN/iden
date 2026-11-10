/**
 * The local provider, as the suite talks to it: sign-in through the real
 * authorization-code + PKCE round trip, and the admin and self-service calls
 * the test cases need. Local only — every URL defaults to this laptop.
 */
import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const ISSUER = process.env.M07_ISSUER ?? "http://localhost:8000";
export const KIOSK = "http://127.0.0.1:8080";
export const REPO = fileURLToPath(new URL("../../../", import.meta.url));
/** Where results go; `M07_RESULTS_DIR` (absolute) keeps a re-run from overwriting the main one. */
export const RESULTS = process.env.M07_RESULTS_DIR
  ? `${process.env.M07_RESULTS_DIR.replace(/[\\/]+$/, "")}/`
  : fileURLToPath(new URL("../../../test-results-m07/", import.meta.url));
export const SCREENSHOTS = `${RESULTS}screenshots/`;
export const MEDIA = fileURLToPath(new URL("../media/", import.meta.url));
const COMPOSE = `${REPO}deploy/docker-compose.yml`;
const STATE_FILE = fileURLToPath(new URL("../.state.json", import.meta.url));
// The dashboard's own client and callback: a sign-in here is exactly the one a
// person makes in the dashboard before creating an enrolment ticket.
const CLIENT_ID = "dashboard";
const CALLBACK = process.env.M07_CALLBACK ?? "http://localhost:3000/console/callback";

export interface State {
  kiosk: { id: string; clientId: string; name: string };
  user: { id: string; email: string; password: string; displayName: string };
}

export function saveState(state: State) {
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

export function loadState(): State {
  return JSON.parse(readFileSync(STATE_FILE, "utf8")) as State;
}

export function adminCredentials() {
  const email = process.env.M07_ADMIN_EMAIL ?? "admin@localhost";
  const password = process.env.M07_ADMIN_PASSWORD;
  if (!password) throw new Error("Set M07_ADMIN_PASSWORD (see kiosk/e2e/README.md).");
  return { email, password };
}

function cookieFrom(response: Response): string {
  return (response.headers.getSetCookie?.() ?? []).map((line) => line.split(";")[0]).join("; ");
}

/**
 * An access token for `email`, by signing in through /oauth2/authorize and
 * /api/v1/auth/login. Its `auth_time` is now, so routes that demand a sign-in
 * within the last five minutes (creating an enrolment ticket) accept it.
 */
export async function signIn(email: string, password: string, scope: string): Promise<string> {
  const verifier = randomBytes(48).toString("base64url");
  const authorize = new URL(`${ISSUER}/oauth2/authorize`);
  authorize.search = new URLSearchParams({
    client_id: CLIENT_ID,
    redirect_uri: CALLBACK,
    response_type: "code",
    scope,
    state: "m07",
    code_challenge: createHash("sha256").update(verifier).digest("base64url"),
    code_challenge_method: "S256",
  }).toString();

  const first = await fetch(authorize, { redirect: "manual" });
  const challengeId = new URL(first.headers.get("location") ?? "").searchParams.get("challenge");
  if (!challengeId) throw new Error(`authorize did not hand over to sign-in: ${first.status}`);

  const login = await fetch(`${ISSUER}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ challengeId, email, password }),
  });
  if (!login.ok) throw new Error(`sign-in as ${email} failed: ${login.status} ${await login.text()}`);
  const step = (await login.json()) as { status: string; resumeUrl: string | null };
  if (step.status !== "complete" || !step.resumeUrl) {
    throw new Error(`${email} needs another sign-in method (${step.status})`);
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
      redirect_uri: CALLBACK,
      code_verifier: verifier,
      client_id: CLIENT_ID,
    }),
  });
  const body = (await token.json()) as { access_token?: string };
  if (!body.access_token) throw new Error(`token exchange failed: ${JSON.stringify(body)}`);
  return body.access_token;
}

/**
 * Tokens are reused while young, because every sign-in counts against the
 * provider's per-address limit (30 per five minutes). A user token is renewed
 * after four minutes so it stays inside the five-minute fresh-sign-in window
 * that creating a ticket demands.
 */
const cached = new Map<string, { token: string; at: number }>();

async function reuse(key: string, maxAgeMs: number, mint: () => Promise<string>) {
  const hit = cached.get(key);
  if (hit && Date.now() - hit.at < maxAgeMs) return hit.token;
  const token = await mint();
  cached.set(key, { token, at: Date.now() });
  return token;
}

export async function adminToken(): Promise<string> {
  return reuse("admin", 8 * 60_000, async () => {
    const { email, password } = adminCredentials();
    const discovery = (await (await fetch(`${ISSUER}/.well-known/openid-configuration`)).json()) as {
      scopes_supported: string[];
    };
    return signIn(email, password, discovery.scopes_supported.join(" "));
  });
}

/** The test user's token, signed in within the last four minutes, for the face routes. */
export async function userToken(): Promise<string> {
  return reuse("user", 4 * 60_000, () => {
    const { email, password } = loadState().user;
    return signIn(email, password, "openid entity:face:read entity:face:write");
  });
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
  if (!response.ok) throw new Error(`${method} ${path} -> ${response.status} ${await response.text()}`);
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export interface KioskRecord {
  id: string;
  status: "never_paired" | "online" | "offline" | "out_of_service";
  pairedAt: string | null;
  lastSeenAt: string | null;
  lastSeenVersion: string | null;
  settings: { idleSeconds: number; inService: boolean; notice: string | null; cameraLabel: string | null };
}

export async function kioskRecord(): Promise<KioskRecord> {
  return api<KioskRecord>(await adminToken(), "GET", `/admin/kiosks/${loadState().kiosk.id}`);
}

export async function setKioskSettings(settings: Partial<KioskRecord["settings"]>) {
  const token = await adminToken();
  const current = await api<KioskRecord>(token, "GET", `/admin/kiosks/${loadState().kiosk.id}`);
  // The settings object is replaced as a whole, so the rest is carried over.
  return api<KioskRecord>(token, "PATCH", `/admin/kiosks/${loadState().kiosk.id}`, {
    settings: { ...current.settings, ...settings },
  });
}

/** A fresh enrolment ticket for the test user, as the dashboard's Security page makes one. */
export async function newTicket(): Promise<string> {
  const created = await api<{ ticket: string }>(await userToken(), "POST", "/entity/face/ticket");
  return created.ticket;
}

export async function faceStatus(): Promise<{ enrolled: boolean }> {
  return api<{ enrolled: boolean }>(await userToken(), "GET", "/entity/face");
}

export function compose(...args: string[]) {
  return execFileSync("docker", ["compose", "-f", COMPOSE, ...args], { encoding: "utf8" });
}

/** Shorten a ticket's life in Redis: the provider stores it under the SHA-256 of the ticket. */
export function expireTicket(ticket: string, seconds: number) {
  const key = `face-ticket:${createHash("sha256").update(ticket).digest("hex")}`;
  const password = process.env.M07_REDIS_PASSWORD ?? "iden";
  const answer = compose("exec", "-T", "redis", "redis-cli", "-a", password, "--no-auth-warning",
    "EXPIRE", key, String(seconds)).trim();
  if (answer !== "1") throw new Error(`EXPIRE ${key} answered ${answer}: the ticket key was not found`);
  return key;
}
