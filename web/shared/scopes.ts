/**
 * The system scope catalogue, mirroring `provider/shared/scopes.py`.
 *
 * These are the scopes the dashboard asks for at `/authorize`. Asking for all
 * of them is correct rather than greedy: the provider resolves
 * `requested ∩ client.grantable ∩ effective_user_scopes` and prunes the rest
 * silently, so a member simply receives a narrower token.
 */

export const ADMIN_SCOPES = [
  "admin:users:read",
  "admin:users:write",
  "admin:groups:read",
  "admin:groups:write",
  "admin:roles:read",
  "admin:roles:write",
  "admin:apis:read",
  "admin:apis:write",
  "admin:scopes:read",
  "admin:scopes:write",
  "admin:clients:read",
  "admin:clients:write",
  "admin:audit:read",
  "admin:profile-fields:read",
  "admin:profile-fields:write",
] as const;

export const ENTITY_SCOPES = [
  "entity:profile:read",
  "entity:profile:write",
  "entity:credentials:write",
  "entity:totp:read",
  "entity:totp:enroll",
  "entity:sessions:read",
  "entity:sessions:revoke",
  "entity:permissions:read",
  "entity:connections:read",
  "entity:connections:revoke",
] as const;

/**
 * Self-service application registration. Its own API rather than an `entity:`
 * scope, so holding it is a deliberate grant rather than something every member
 * gets — see the note in `provider/shared/scopes.py`.
 */
export const DEVELOPER_SCOPES = ["developer:clients:read", "developer:clients:write"] as const;

/**
 * Not in the DB and never carry an audience — see `scope_resolver.OIDC_SCOPES`.
 *
 * `offline_access` is what asks for a refresh token (OIDC Core Section 11). The
 * dashboard needs one: `automaticSilentRenew` renews from it, and without the
 * scope the provider issues none and the session ends at the first access
 * token's expiry.
 */
export const OIDC_SCOPES = ["openid", "profile", "email", "offline_access"] as const;

export type AdminScope = (typeof ADMIN_SCOPES)[number];
export type EntityScope = (typeof ENTITY_SCOPES)[number];
export type DeveloperScope = (typeof DEVELOPER_SCOPES)[number];
export type Scope = AdminScope | EntityScope | DeveloperScope;

/** What the dashboard requests at `/authorize`, as the space-delimited string. */
export const DASHBOARD_SCOPE = [
  ...OIDC_SCOPES,
  ...ADMIN_SCOPES,
  ...ENTITY_SCOPES,
  ...DEVELOPER_SCOPES,
].join(" ");

/** Parses the `scope` claim, which is space-delimited per RFC 6749. */
export function parseScopes(claim: string | undefined): Set<string> {
  return new Set(claim ? claim.split(" ").filter(Boolean) : []);
}
