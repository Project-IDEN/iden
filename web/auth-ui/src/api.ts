import { createClient, get, readIssuer, type components } from "@iden/shared";

export type Challenge = components["schemas"]["ChallengeResponse"];
export type AuthStep = components["schemas"]["AuthStepResponse"];
export type ConsentResult = components["schemas"]["ConsentResponse"];

const issuer = readIssuer(import.meta.env.VITE_IDEN_ISSUER);

/**
 * Cookies are included on every call: login and consent set `iden_session`, and
 * the browser stores it only for a credentialed request. This is also why the
 * provider's CORS allowlist has to name this origin exactly — a wildcard is not
 * permitted with credentials.
 */
const client = createClient({ issuer, withCredentials: true });

/**
 * Ends the session with a POST, which a cross-site page cannot send with the
 * cookie. Returns where to go next: the application's registered address when
 * the provider redirected there, or null when there is nowhere to go.
 */
export async function signOut(params: URLSearchParams): Promise<string | null> {
  const response = await fetch(new URL("/oauth2/logout", issuer), {
    method: "POST",
    body: params,
    credentials: "include",
    redirect: "manual",
  });
  if (response.type !== "opaqueredirect") return null;
  // The provider redirects only to an address registered on the client, so
  // following the one asked for is following the one it approved.
  const target = new URL(params.get("post_logout_redirect_uri") ?? "");
  const state = params.get("state");
  if (state) target.searchParams.set("state", state);
  return target.toString();
}

export function readChallenge(challengeId: string): Promise<Challenge> {
  return get<Challenge>(client, `/api/v1/auth/challenge/${challengeId}`);
}

export async function signIn(body: {
  challengeId: string;
  email: string;
  password: string;
}): Promise<AuthStep> {
  const response = await client.post<AuthStep>("/api/v1/auth/login", body);
  return response.data;
}

export async function submitTotp(body: { challengeId: string; code: string }): Promise<AuthStep> {
  const response = await client.post<AuthStep>("/api/v1/auth/totp", body);
  return response.data;
}

export type FaceChallenge = components["schemas"]["FaceChallengeResponse"];

export async function startFaceCheck(challengeId: string): Promise<FaceChallenge> {
  const response = await client.post<FaceChallenge>("/api/v1/auth/biometric/challenge", {
    challengeId,
  });
  return response.data;
}

/** Multipart: the frames go to the provider, which forwards them to the engine. */
export async function submitFace(body: {
  challengeId: string;
  faceChallengeId: string;
  frames: Blob[];
}): Promise<AuthStep> {
  const form = new FormData();
  form.append("challengeId", body.challengeId);
  form.append("faceChallengeId", body.faceChallengeId);
  body.frames.forEach((frame, index) => form.append("frames", frame, `${index}.jpg`));
  const response = await client.post<AuthStep>("/api/v1/auth/biometric", form);
  return response.data;
}

export async function decideConsent(body: {
  challengeId: string;
  approved: boolean;
}): Promise<ConsentResult> {
  const response = await client.post<ConsentResult>("/api/v1/auth/consent", body);
  return response.data;
}
