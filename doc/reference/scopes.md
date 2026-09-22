# Scopes

The permissions IDEN defines for itself. Everything here is marked system-defined and cannot be
renamed or deleted — an administrator who deleted `admin:roles:write` would lock the organization out
of its own deployment.

Your own APIs define their own permissions; see
[Validate tokens in your API](../guides/protect-an-api.md).

## Administration

Managing the deployment. The `administrator` role carries all of them.

| Scope | Grants |
|---|---|
| `admin:users:read` | View users, their roles, and their direct grants. |
| `admin:users:write` | Create, update, and delete users, reset their passwords, and clear a lost authenticator. |
| `admin:grants:write` | Assign roles and individual scopes to a person. Split out of `admin:users:write`, because assigning permissions is the one administrative act that raises somebody's authority — see [Delegation](#delegation). |
| `admin:groups:read` | View groups, their members, and their roles. |
| `admin:groups:write` | Create, update, and delete groups and membership. |
| `admin:roles:read` | View roles and the scopes they bundle. |
| `admin:roles:write` | Create, update, and delete roles and their scopes. |
| `admin:apis:read` | View registered resource APIs. |
| `admin:apis:write` | Register, update, and delete resource APIs. |
| `admin:scopes:read` | View the scopes defined under an API. |
| `admin:scopes:write` | Define, update, and delete scopes under an API. |
| `admin:clients:read` | View registered OAuth clients. |
| `admin:clients:write` | Register clients and rotate their secrets. |
| `admin:audit:read` | Read the audit log. |
| `admin:profile-fields:read` | View the organization's profile schema. |
| `admin:profile-fields:write` | Define the fields this organization collects about people. |

## Self-service

What a person may do to their own account. The `member` role carries all of them.

| Scope | Grants |
|---|---|
| `entity:profile:read` | View your own profile. |
| `entity:profile:write` | Update your own profile. |
| `entity:credentials:write` | Change your own password. |
| `entity:totp:read` | View the status of your authenticator app. |
| `entity:totp:enroll` | Set up or remove your authenticator app. |
| `entity:sessions:read` | See where you are signed in. |
| `entity:sessions:revoke` | Sign yourself out of other sessions. |
| `entity:permissions:read` | See your own roles, groups, and permissions. |
| `entity:connections:read` | See which applications have access. |
| `entity:connections:revoke` | Withdraw an application's access. |

## Developer self-service

Registering your own application against someone else's IDEN. The `developer` role carries these
plus every self-service scope; no account has them by default. See
[Let people register their own applications](../guides/self-service-registration.md).

| Scope | Grants |
|---|---|
| `developer:clients:read` | View the applications you registered. |
| `developer:clients:write` | Register your own applications and rotate their secrets. |

These are their own API rather than `entity:` scopes on purpose: `member` carries every `entity:`
scope, so putting them there would make every account a developer.

## Biometrics

Seeded only when `IDEN_BIOMETRIC_ENABLED=true`. The module itself is not built yet.

| Scope | Grants |
|---|---|
| `biometric:enroll` | Enrol a face template. |
| `biometric:verify` | Verify a face against a claimed identity. |
| `biometric:search` | Identify a face against all enrolled templates. |
| `biometric:liveness` | Check whether a captured face is live. |

## The OIDC scopes

Not IDEN's to define — these come from the specification and behave as clients expect.

| Scope | Effect |
|---|---|
| `openid` | Required to receive an ID token at all. Without it the flow is plain OAuth 2.0. |
| `profile` | Releases `name` and `preferred_username`. |
| `email` | Releases `email` and `email_verified`. |
| `offline_access` | Asks for a refresh token, so the application keeps working while the person is away from it. The client must also allow the `refresh_token` grant; without both, no refresh token is issued. |

## Delegation

Holding a scope that assigns permissions does not let you assign *every* permission.

**An `admin:` or `biometric:` scope can only be granted by somebody who already holds it.** The
check runs against the caller's own token, not their account — so an administrator working through a
narrowly-scoped client cannot delegate past that token, and the rule applies unchanged to
`client_credentials`, where there is no person at all. Anything else is refused with
`403 cannot_delegate`.

It covers every route a scope can travel, not only the obvious one:

- naming a scope directly, or a role that contains it
- creating a user that already holds either
- giving a group a role, or adding somebody to a group that has one
- changing what a role means, which promotes everyone already holding it
- registering a client that holds it, or adding it to one — a confidential client holding a scope in
  its own right is a `client_credentials` request away from using it

**Your organization's own scopes are unrestricted**, and deliberately. An identity provider exists so
that administrators can grant permissions they do not personally need; requiring a registrar to hold
`attendance:records:write` before granting it would mean holding every permission in the
organization. `entity:` and `developer:` are unrestricted for a different reason: they are
self-service, so granting one raises the grantee's authority over themselves and the granter's over
nobody.

## Acting on somebody above you

The mirror of the same idea, and the half that is easy to miss. Stopping an administrator granting
what they lack achieves nothing if they can take it from whoever already has it instead.

**You may only administer people and applications that are not above you.** If the target holds an
`admin:` or `biometric:` scope the caller does not, the request is refused with
`403 cannot_administer`. It applies to every write:

- a person: updating them, assigning their roles or scopes, resetting their password, clearing their
  authenticator, deleting them — because a password reset plus a cleared authenticator is a way to
  sign in as them
- an application: changing it, rotating its secret, deleting it — because a scope a client holds in
  its own right becomes usable as soon as somebody adds the `client_credentials` grant and takes the
  secret, and neither of those is a scope assignment

A client's `grantable` scopes do not count as authority it holds. Those reach a token only through
`/authorize`, where they are intersected with what the signed-in person holds, so they can never
exceed somebody's existing permissions — and counting them would leave a limited administrator
unable to touch the deployment's own dashboard client, which is grantable for everything and holds
nothing.

## Putting it together

What the two rules buy you is a help-desk account. Give it `admin:users:read`, `admin:users:write` and the
group scopes, and withhold `admin:grants:write`: it can create people, rename them, deactivate them,
reset their passwords and clear a lost authenticator, and it cannot make anyone an administrator —
including itself, and including by way of an administrator who already is one.
