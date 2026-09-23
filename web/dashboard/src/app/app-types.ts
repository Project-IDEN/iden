/**
 * The four shapes an OIDC client comes in.
 *
 * One question rather than three. "Can it keep a secret?" and "which grant?"
 * are not independent decisions somebody makes — they follow from what kind of
 * application this is, and every other OIDC console asks it this way for that
 * reason. The consequences are derived here, once.
 *
 * Shared by both registration flows, so a hint corrected in one is corrected in
 * the other.
 */
export const APP_TYPES = {
  web: {
    label: "Web application",
    hint: "Server-side app — Next.js, Django, Rails. Keeps a secret.",
    clientType: "confidential",
    grants: ["authorization_code", "refresh_token"],
    summary: "Confidential · authorization code + PKCE",
  },
  spa: {
    label: "Single-page application",
    hint: "Runs in the browser — React, Vue, Angular. No secret; PKCE proves it.",
    clientType: "public",
    grants: ["authorization_code", "refresh_token"],
    summary: "Public · authorization code + PKCE",
  },
  native: {
    label: "Native or mobile app",
    hint: "iOS, Android, desktop. Anything a user can read the source of is public.",
    clientType: "public",
    grants: ["authorization_code", "refresh_token"],
    summary: "Public · authorization code + PKCE",
  },
  service: {
    label: "Machine-to-machine",
    hint: "A backend job or a kiosk acting as itself. No person signs in.",
    clientType: "confidential",
    grants: ["client_credentials"],
    summary: "Confidential · client credentials",
  },
} as const;

export type AppType = keyof typeof APP_TYPES;

/**
 * What self-service may register — everything but machine-to-machine.
 *
 * That one is absent because `/developer/clients` fixes the grants to
 * authorization code + refresh. A `client_credentials` client acts as itself
 * with nobody's permissions narrowing it, which is an administrator's decision.
 * The other three differ only in advice: two of them resolve to the same public
 * client, and the redirect URI worth registering is not the same for a browser
 * as for a phone.
 */
export const SELF_SERVICE_TYPES = ["web", "spa", "native"] as const satisfies readonly AppType[];
