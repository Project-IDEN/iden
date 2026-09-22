# Endpoints

Generated from the running application. The interactive version, with request and response bodies,
is at `/docs` on any deployment — it is the same data, and it is always current.

Every `/admin/*` and `/entity/*` route is gated by a permission named in its description there.

### Admin — apis

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/apis` | List resource APIs |
| `POST` | `/admin/apis` | Register a resource API |
| `DELETE` | `/admin/apis/{api_id}` | Delete a resource API |
| `GET` | `/admin/apis/{api_id}` | Read a resource API |
| `PATCH` | `/admin/apis/{api_id}` | Update a resource API |

### Admin — audit

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/audit` | Read the audit log |

### Admin — clients

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/clients` | List OAuth clients |
| `POST` | `/admin/clients` | Register an OAuth client |
| `DELETE` | `/admin/clients/{client_id}` | Delete an OAuth client |
| `GET` | `/admin/clients/{client_id}` | Read an OAuth client |
| `PATCH` | `/admin/clients/{client_id}` | Update an OAuth client |
| `POST` | `/admin/clients/{client_id}/rotate-secret` | Rotate a client secret |
| `PUT` | `/admin/clients/{client_id}/scopes` | Set a client's scopes |

### Admin — groups

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/groups` | List groups |
| `POST` | `/admin/groups` | Create a group |
| `DELETE` | `/admin/groups/{group_id}` | Delete a group |
| `GET` | `/admin/groups/{group_id}` | Read a group |
| `PATCH` | `/admin/groups/{group_id}` | Rename or describe a group |
| `GET` | `/admin/groups/{group_id}/members` | List a group's members |
| `POST` | `/admin/groups/{group_id}/members` | Add members |
| `DELETE` | `/admin/groups/{group_id}/members/{user_id}` | Remove a member |
| `PUT` | `/admin/groups/{group_id}/roles` | Set a group's roles |

### Admin — profile fields

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/profile-fields` | List profile fields |
| `POST` | `/admin/profile-fields` | Define a profile field |
| `GET` | `/admin/profile-fields/presets` | Ready-made definitions to start from. Templates — nothing exists until you post one back |
| `DELETE` | `/admin/profile-fields/{field_id}` | Delete a profile field |
| `GET` | `/admin/profile-fields/{field_id}` | Read a profile field |
| `PATCH` | `/admin/profile-fields/{field_id}` | Update a profile field |

### Admin — roles

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/roles` | List roles |
| `POST` | `/admin/roles` | Create a role |
| `DELETE` | `/admin/roles/{role_id}` | Delete a role |
| `GET` | `/admin/roles/{role_id}` | Read a role |
| `PATCH` | `/admin/roles/{role_id}` | Rename or describe a role |
| `PUT` | `/admin/roles/{role_id}/scopes` | Set a role's scopes |

### Admin — scopes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/apis/{api_id}/scopes` | List an API's scopes |
| `POST` | `/admin/apis/{api_id}/scopes` | Define a scope |
| `DELETE` | `/admin/scopes/{scope_id}` | Delete a scope |
| `GET` | `/admin/scopes/{scope_id}` | Read a scope |
| `PATCH` | `/admin/scopes/{scope_id}` | Update a scope's description |

### Admin — users

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/users` | List users |
| `POST` | `/admin/users` | Create a user |
| `DELETE` | `/admin/users/{user_id}` | Delete a user |
| `GET` | `/admin/users/{user_id}` | Read a user |
| `PATCH` | `/admin/users/{user_id}` | Update a user |
| `GET` | `/admin/users/{user_id}/effective-scopes` | Explain a user's permissions |
| `GET` | `/admin/users/{user_id}/profile` | Read a user's profile values |
| `PATCH` | `/admin/users/{user_id}/profile` | Set a user's profile values |
| `POST` | `/admin/users/{user_id}/reset-password` | Reset a user's password |
| `PUT` | `/admin/users/{user_id}/roles` | Set a user's roles |
| `PUT` | `/admin/users/{user_id}/scopes` | Set a user's direct scope grants |
| `DELETE` | `/admin/users/{user_id}/totp` | Clear a user's authenticator |

### Sign-in and recovery

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/biometric` | Sign in with a face |
| `GET` | `/api/v1/auth/challenge/{challenge_id}` | Read a pending login or consent challenge |
| `POST` | `/api/v1/auth/consent` | Approve or deny a consent request |
| `POST` | `/api/v1/auth/login` | Sign in with a password |
| `POST` | `/api/v1/auth/password-reset` | Ask for a password reset link |
| `POST` | `/api/v1/auth/password-reset/confirm` | Set a new password with a reset link |
| `POST` | `/api/v1/auth/totp` | Verify a time-based one-time code |

### Entity — connections

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/entity/connections` | See which applications have access |
| `DELETE` | `/entity/connections/{client_id}` | Withdraw an application's access |

### Entity — credentials

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/entity/credentials/email` | Change your email address |
| `POST` | `/entity/credentials/password` | Change your password |

### Entity — permissions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/entity/permissions` | See what you are allowed to do |

### Entity — profile

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/entity/profile` | Read your own profile |
| `PATCH` | `/entity/profile` | Update your own profile |
| `GET` | `/entity/profile/schema` | Read the shape of your profile |
| `PUT` | `/entity/profile/photo` | Set your profile photo |
| `DELETE` | `/entity/profile/photo` | Remove your profile photo |

### Entity — sessions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/entity/sessions` | See where you are signed in |
| `DELETE` | `/entity/sessions/{session_id}` | Sign one session out |

### Entity — totp

| Method | Path | Purpose |
|---|---|---|
| `DELETE` | `/entity/totp` | Remove your authenticator |
| `GET` | `/entity/totp` | Is an authenticator set up? |
| `POST` | `/entity/totp/confirm` | Finish setting up an authenticator |
| `POST` | `/entity/totp/enroll` | Start setting up an authenticator |

### Media

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/media/avatars/{name}` | Fetch a profile photo. Public — it is what the `picture` claim points at, and an `<img>` cannot send a token |

### Service

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health, always `200` — detail in the body |
| `GET` | `/health/live` | Liveness probe. Restart on a failure here |
| `GET` | `/health/ready` | Readiness probe. `503` when a dependency is unreachable; drain, do not restart |

### OAuth 2.0 and OIDC

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/oauth2/authorize` | Start an authorization request |
| `POST` | `/oauth2/introspect` | Inspect a token — your own tokens only |
| `GET` `POST` | `/oauth2/logout` | End the session everywhere. Prefer `POST`: it keeps `id_token_hint` out of browser history and the `Referer` header |
| `POST` | `/oauth2/revoke` | Revoke a token |
| `POST` | `/oauth2/token` | Exchange a grant for tokens |
| `GET` `POST` | `/oauth2/userinfo` | Claims about the signed-in user. `POST` also accepts the token as an `access_token` form field |

### Discovery

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/.well-known/openid-configuration` | OpenID provider metadata |
| `GET` | `/.well-known/oauth-authorization-server` | The same document, where RFC 8414 puts it. A pure OAuth 2.0 client with no OIDC layer looks only here |
| `GET` | `/.well-known/jwks.json` | Public signing keys, one JWK per `kid` |
