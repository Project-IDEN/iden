# Roadmap

The full build plan and every open issue live in
[`provider/PLAN.md`](https://github.com/Project-IDEN/iden/blob/dev/provider/PLAN.md). This is
the summary.

## Phases

| Phase | Focus | Status |
|---|---|---|
| 0 | Foundation — config, database, models, security, seed | :material-check-circle-outline: Done |
| 1 | AuthZ core — discovery, JWKS, authorize + PKCE, token, userinfo, sign-in | :material-check-circle-outline: Done |
| 2 | Admin — users, groups, roles, APIs, scopes, clients | :material-check-circle-outline: Done |
| 3 | SSO — `prompt`, `max_age`, `sid`, single sign-out | :material-check-circle-outline: Done |
| 4 | Self-service — profile, org-defined fields, credentials, TOTP, recovery | :material-check-circle-outline: Done |
| 5 | Biometrics — enrollment, verification, liveness | :material-pause-circle-outline: On hold |
| 6 | Hardening — Docker, security headers, error contract, probes, coverage review | :material-check-circle-outline: Done |
| 7 | Frontends — the sign-in UI and the dashboard | :material-check-circle-outline: Done |
| 8 | Kiosk — device registration and enrollment | :material-circle-outline: Planned |

Phase 7 shipped both browser applications: `auth-ui` (password, TOTP, consent and recovery) and the
dashboard (self-service plus all seven admin resources, each gated on its read scope). Their own
phased plan, with the same *Status* notes, is
[`web/PLAN.md`](https://github.com/Project-IDEN/iden/blob/dev/web/PLAN.md). What is outstanding there
is a visual review: the screens have been verified functionally and in containers, not walked through
in a browser with a designer's eye.

Migrations, the audit log, and rate limiting were all pulled forward out of Phase 6. Each was
scheduled late and each got more expensive with every phase that passed — history not written is
lost, and an unmigrated schema needs manual surgery.

Phase 5 is on hold rather than next: the biometric module is the only part with an external
dependency, and everything it plugs into already exists. Phase 7 was taken ahead of it for the same
reason in reverse — the provider had no human-usable surface, and a system nobody can sign into is
hard to evaluate.

## Open issues

| | Issue | Consequence |
|---|---|---|
| **KI-7** | `admin:*` is all-or-nothing | No "administrator who cannot create administrators". Anyone with `admin:users:write` can grant themselves anything. |
| **KI-9** | One token can carry several audiences | Ask for admin and entity scopes together and both are in `aud`. Standard, but a compromised resource server could replay the token at the other. |
| **KI-17** | An audit row is not atomic with its change | Written just after; a database failure in between loses the record. Logged loudly. |

## Federation

*Sign in with Google, or with a campus SAML server* — deliberately out of scope, and worth explaining
rather than leaving implied.

The protocol is the easy part. The hard part is **account linking**: matching an incoming federated
identity to an existing local account by email address is the obvious shortcut and a well-known
account takeover, because it trusts the upstream provider's word about an address it may not own.

The safe rules — link only on a verified address from a provider trusted for that domain, or require
an explicit link from an already signed-in session — are what make it a phase of work rather than an
afternoon's.

## What is deliberately not planned

| | Why |
|---|---|
| **Multi-tenancy** | The single-organization decision is what removes an entire dimension of complexity from every model and query. Run two deployments. |
| **SAML as an identity provider** | A large amount of XML signing for a protocol IDEN would otherwise never touch. Only worth it if a system you must integrate with demands it. |
| **Account deletion by the account holder** | In a single-organization deployment the organization owns the identity. A deactivation *request* is the affordance to build if one is wanted. |
| **Implicit and password grants** | Discouraged by OAuth 2.1 and unnecessary given the two flows that exist. |
