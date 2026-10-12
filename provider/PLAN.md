# IDEN Provider — Build Plan

The phased plan for building the IDEN backend (`provider/`). Read
[README.md](README.md) for the reference material — data model, endpoints, env vars, conventions —
and this file for the **order of work**.

Each phase states its goal, the files it creates, the endpoints it delivers, and a **Done when**
check you can run by hand. Build phases in order: each one is runnable and verifiable before the next
begins.

> Scope note: this plan covers the backend only. The `auth-ui` and `dashboard` frontends are planned
> in [web/PLAN.md](../web/PLAN.md), and the kiosk devices separately; both consume what is built here.

---

## Table of Contents

- [Ground rules](#ground-rules)
- [Target package layout](#target-package-layout)
- [Phase 0 — Foundation](#phase-0--foundation)
- [Phase 1 — AuthZ core](#phase-1--authz-core)
- [Phase 2 — Admin RS (identity & access control)](#phase-2--admin-rs-identity--access-control)
- [Phase 3 — SSO: session control and single sign-out](#phase-3--sso-session-control-and-single-sign-out)
- [Phase 4 — Entity RS (self-service)](#phase-4--entity-rs-self-service)
- [Phase 5 — Biometric module](#phase-5--biometric-module)
- [Phase 6 — Hardening](#phase-6--hardening)
- [Session provenance — last seen, device, address](#session-provenance--last-seen-device-address)
- [Known issues](#known-issues)
- [Why this order](#why-this-order)

---

## Ground rules

These apply to every phase. They repeat what `.claude/CLAUDE.md` and `CODING_STYLE.md` already say,
collected here so a phase can be executed without flipping between files.

1. **Feature packages, not layers.** A resource lives in one directory:
   `routes.py` (HTTP, no DB), `schemas.py` (Pydantic DTOs), `service.py` (DB logic, FastAPI-free),
   `errors.py` (domain exceptions). Routes translate domain exceptions into `HTTPException`.
2. **Every endpoint documents itself.** Explicit `response_model`, explicit `status_code` for
   non-200 successes, `summary`, `description`, `responses={...}` for documented failures, `tags` on
   the router, `Field(description=...)` on non-obvious fields, `Literal[...]` for enums. The
   required scope is named in the description **and** enforced with `Depends(require_scope(...))`.
3. **Simplest thing that reads well.** Three similar lines beat a premature abstraction. No
   defensive code for states that cannot happen; validate at boundaries and trust internal callers.
4. **Comment only the why.** A hidden constraint, a surprising invariant, a spec requirement worth
   citing. Never narrate what the code does.
5. **`async` only for real I/O.** Scope-set maths, PKCE hashing, and claim assembly are synchronous
   functions called from async handlers.
6. **Dependencies via `uv add`** from `provider/`. Never hand-edit the `pyproject.toml` dependency
   list.
7. **New resource ⇒ new scope.** Add it to `shared/scopes.py`, include it in the seeded system
   catalogue, and re-run the seed.
8. **Tests ship with the phase that introduces the code**, not at the end. Pure logic gets unit
   tests (no database, no fixtures); every endpoint gets at least a success case, an authorization
   failure, and its most interesting failure mode. `uv run pytest` must be green before a phase is
   called done.
9. **A regression test must be shown to fail without the fix.** Revert the change, watch it go red,
   restore it. Two of the concurrency tests written for KI-3 passed *without* the lock — they
   depended on timing that happened to favour them, and would have certified a bug as fixed. A test
   that cannot fail is worse than no test, because it stops anyone looking again.

### Testing

Tests live in `provider/tests/` and run against a real PostgreSQL database (`iden_test`), created
once per session and truncated between tests. Not SQLite: the models use PostgreSQL arrays and
UUIDs, and a test passing on a different engine than production proves less than it appears to.
Redis uses logical database 15, flushed around every test, so a run can never disturb a developer's
live session.

```bash
uv run pytest              # everything
uv run pytest -q tests/test_scope_resolver.py
```

The `client` fixture drives the app in-process over ASGI — no live server, no port. Its `base_url`
matches `IDEN_ISSUER` on purpose: `/authorize` builds absolute resume URLs from the issuer, and a
cookie set on one host is not sent to another, so a mismatch silently breaks the login round-trip.

The `catalogue` fixture seeds through the **real** functions in `scripts/seed.py`, so drift between
the seed and the tests surfaces as a failure rather than as a surprise in production. The schema is
built by running the migrations, for the same reason: it is the path a deployment takes.

`test_migrations.py` guards the one thing that otherwise rots quietly: it fails when the models and
the migrations disagree.

---

## Target package layout

```text
provider/
├── PLAN.md
├── README.md
├── pyproject.toml
├── scripts/
│   ├── __init__.py
│   ├── seed.py                 # idempotent dev bootstrap
│   └── gen_keys.py             # generate a signing keypair for local dev
└── src/provider/
    ├── core/                   # cross-cutting infrastructure
    │   ├── app.py              # FastAPI app, middleware, router mounting
    │   ├── config.py           # Settings
    │   ├── logging.py          # structlog wiring
    │   ├── router.py           # root APIRouter
    │   ├── db.py               # async engine, session, DBSessionDep
    │   ├── redis.py            # redis client + RedisDep
    │   ├── audit.py            # AuditMiddleware, set_actor(), record()
    │   ├── ratelimit.py        # per-address and per-account limits
    │   ├── notifier.py         # outbound messages; logs in dev
    │   ├── security.py         # argon2 hashing, random token generation
    │   ├── crypto.py           # signing keys, JWKS, JWT sign/verify
    │   ├── auth.py             # require_scope(), require_fresh_auth()
    │   ├── errors.py           # base domain exception + HTTP error contract
    │   └── schemas.py          # CamelCaseBaseModel, shared response envelopes
    ├── shared/
    │   ├── models.py           # every SQLAlchemy model — one source of truth
    │   ├── enums.py            # ClientType, GrantType, AmrMethod, AcrLevel, …
    │   ├── profile.py          # profile value validation and casting
    │   └── scopes.py           # the seeded system API/scope/role catalogue
    ├── authz/
    │   ├── discovery/          # /.well-known/*
    │   ├── oauth/              # /oauth2/*
    │   ├── login/              # /api/v1/auth/login · /totp · /biometric
    │   ├── consent/            # /api/v1/auth/consent
    │   ├── logout/             # back-channel logout fan-out
    │   ├── recovery/           # /api/v1/auth/password-reset
    │   └── services/
    │       ├── scope_resolver.py
    │       ├── token_service.py
    │       ├── session_store.py
    │       ├── challenge_store.py
    │       ├── auth_methods.py     # registry: pwd · otp · face
    │       └── pkce.py
    ├── admin/
    │   ├── users/  groups/  roles/  apis/  scopes/  clients/
    │   ├── audit/                  # read-only
    │   └── profile_fields/
    ├── entity/
    │   ├── deps.py                 # CurrentUserDep — subject from the token
    │   ├── profile/  credentials/  totp/  sessions/  permissions/
    │   └── connections/
    └── biometric/                  # Phase 5: kiosk API, challenges, tickets
        ├── engine_client.py  challenges.py  tickets.py
        └── service.py  routes.py
```

Each leaf directory under `admin/`, `entity/`, and `biometric/` is a feature package with the four
files from ground rule 1.

---

## Phase 0 — Foundation

**Goal:** a running app with a real database, real models, hashing, signing keys, and a seed script
that bootstraps the deployment. No OAuth yet.

### 0.1 Dev infrastructure

Phase 0 cannot be verified without a database, so the dev half of Docker Compose comes first:
`deploy/docker-compose.yml` with `pgvector/pgvector:pg18` and `redis:8-alpine`, both health-checked.

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Postgres 18 moved its recommended volume mount to `/var/lib/postgresql` (not `/var/lib/postgresql/data`);
mounting the old path makes the container refuse to start. The provider image, nginx, minio, and the
engine stay in Phase 6.

### 0.2 Clean up the skeleton

Three things in the current skeleton need fixing before building on them:

| Problem | Fix |
|---|---|
| `src/provider/schemas.py/` is a **directory** named `schemas.py`, holding `camel_case_base_model.py` | Delete the directory; move `CamelCaseBaseModel` into `core/schemas.py` |
| `src/provider/database/` holds an empty `models.py`, but `.claude/CLAUDE.md` specifies `shared/models.py` | Delete `database/`; create `shared/models.py` |
| `src/provider/resources/` and `utils/` are empty placeholders | Delete both; add directories when there is something to put in them |
| `pydantic-settings` is imported by `core/config.py` but is only a transitive dependency | `uv add pydantic-settings` |

Also add: `uv add "redis[hiredis]" pyjwt cryptography pyotp python-multipart`.
(`argon2-cffi` is already present. `authlib` was removed: its authorization-server integrations
are Flask- and Django-only, so it would buy an adapter layer rather than an implementation.)

### 0.3 Configuration — `core/config.py`

Extend the existing `Settings` with everything later phases need. Full table in
[README.md — Configuration](README.md#configuration). Groups:

- **App** — `iden_env`, `iden_log_level`, `iden_api_prefix`, `iden_allowed_admin_origins` *(existing)*
- **Issuer** — `iden_issuer`, `iden_auth_ui_base_url`
- **Storage** — `iden_database_url`, `iden_redis_url`
- **Crypto** — `iden_signing_key_dir`, `iden_signing_algorithm` (`RS256`)
- **Lifetimes** — `iden_access_token_ttl` (600s), `iden_id_token_ttl` (600s),
  `iden_refresh_token_ttl` (30d), `iden_auth_code_ttl` (60s), `iden_session_ttl` (24h),
  `iden_challenge_ttl` (600s)
- **Bootstrap** — `iden_bootstrap_admin_email`, `iden_bootstrap_admin_password` (generated and
  printed when unset)
- **Biometric** — `iden_biometric_enabled` (default `false`), `iden_engine_base_url`

Mirror every field into `.env.example`.

### 0.4 Infrastructure modules

- **`core/db.py`** — `create_async_engine`, `async_sessionmaker`, a `get_db_session` dependency that
  yields a session and rolls back on exception, and the alias `DBSessionDep`.
- **`core/redis.py`** — a module-level async client created in the app lifespan, plus `RedisDep`.
- **`core/security.py`** — `hash_secret()` / `verify_secret()` using argon2id
  (time=1, mem=64MB, threads=4), and `generate_token(nbytes)` for codes, refresh tokens, and client
  secrets. **All** password and client-secret hashing goes through this module.
- **`core/crypto.py`** — load the signing keypair from `iden_signing_key_dir`, expose
  `sign_jwt(claims)`, `verify_jwt(token)`, and `jwks()` returning the public JWK set with a `kid`
  per key. Written for multiple keys from day one so rotation is a config change, not a rewrite.
- **`core/errors.py`** — `IdenError` base with `code`/`message`, and the JSON error contract every
  route returns.
- **`core/schemas.py`** — `CamelCaseBaseModel` (moved), plus shared paging schemas.

### 0.5 The data model — `shared/models.py`

One file, one source of truth. All primary keys are UUIDv7-ish (`uuid.uuid7()`, Python 3.14) unless
noted. Every table carries `created_at` / `updated_at`.

**Identity**

| Model | Key columns |
|---|---|
| `User` | `email` (unique), `username` (unique), `password_hash`, `display_name`, `is_active`, `email_verified_at`, `last_login_at` |
| `Group` | `name` (unique), `description` |
| `UserGroup` | `user_id`, `group_id` — composite PK, flat membership |
| `TotpCredential` | `user_id`, `secret_encrypted`, `confirmed_at` |

**Access control**

| Model | Key columns |
|---|---|
| `ResourceApi` | `name`, `audience` (unique URI), `description`, `is_system` |
| `Scope` | `api_id` → `ResourceApi`, `value`, `description`, `is_system` — unique on `(api_id, value)` |
| `Role` | `name` (unique), `description`, `is_system` |
| `RoleScope` | `role_id`, `scope_id` |
| `UserRole` | `user_id`, `role_id` |
| `GroupRole` | `group_id`, `role_id` |
| `UserScope` | `user_id`, `scope_id` — direct one-off grants |

**OAuth**

| Model | Key columns |
|---|---|
| `Client` | `client_id` (unique), `name`, `client_type` (`public`/`confidential`), `client_secret_hash`, `redirect_uris` (array), `allowed_grants` (array), `skip_consent`, `is_system` |
| `ClientScope` | `client_id`, `scope_id`, `grantable` (may be requested on behalf of a user) vs `granted` (held by the client itself for `client_credentials`) |
| `AuthorizationCode` | `code_hash`, `client_id`, `user_id`, `redirect_uri`, `scope`, `code_challenge`, `code_challenge_method`, `nonce`, `acr`, `amr`, `expires_at`, `used_at` |
| `RefreshToken` | `token_hash`, `client_id`, `user_id`, `scope`, `family_id`, `rotated_to_id`, `expires_at`, `revoked_at` |
| `ConsentGrant` | `user_id`, `client_id`, `scopes` (array), `granted_at` — so a user is asked once |

Not in Postgres: sessions, login/consent challenges, and the `jti` denylist live in Redis with TTLs.

**Design notes worth writing into the code as comments:**
- `is_system` protects IDEN's own APIs, scopes, roles, and clients from deletion. Without it an
  admin could delete `admin:roles:write` and lock the organization out permanently.
- Codes and refresh tokens are stored **hashed**, exactly like passwords — a database read must not
  yield usable credentials.
- `RefreshToken.family_id` + `rotated_to_id` implement rotation with **reuse detection**: presenting
  an already-rotated token revokes the entire family, on the assumption it was stolen.

### 0.6 The system catalogue — `shared/scopes.py`

A plain declarative structure — no logic — listing the APIs, scopes, and roles the seed upserts.

| API | Audience | Scopes |
|---|---|---|
| `admin` | `{issuer}/admin` | `admin:users:read/write`, `admin:groups:read/write`, `admin:roles:read/write`, `admin:apis:read/write`, `admin:scopes:read/write`, `admin:clients:read/write` |
| `entity` | `{issuer}/entity` | `entity:profile:read/write`, `entity:credentials:write`, `entity:totp:read/enroll`, `entity:sessions:read/revoke`, `entity:permissions:read` |
| `biometric` | `{issuer}/biometric` | `biometric:enroll` |

Seeded roles: **`administrator`** (every `admin:*` and `entity:*` scope) and **`member`** (every
`entity:*` scope). Both `is_system`.

### 0.7 Seed script — `scripts/seed.py`

Idempotent, safe to re-run at any time. The schema is not its job — Alembic owns that, and the seed
exits with an instruction if the database has not been migrated (see [KI-15](#resolved)):

1. Refuse to run unless `alembic_version` exists
2. Upsert system APIs, scopes, and roles from `shared/scopes.py`
3. Upsert the bootstrap `dashboard` client (public, PKCE, `skip_consent=true`) and the `kiosk` client
   (confidential, `client_credentials`) — print the kiosk secret once
5. Create the bootstrap admin user with the `administrator` role; print the generated password once

Run `uv run alembic upgrade head` then `uv run python -m scripts.seed`, both from `provider/`.

`scripts/gen_keys.py` writes an RSA keypair into `iden_signing_key_dir` for local development.

### 0.8 App wiring — `core/app.py`

Keep the existing request-id + structlog middleware. Add: the DB engine and Redis client to the
lifespan, a `GET /health` returning DB and Redis reachability, and an exception handler translating
`IdenError` into the JSON error contract.

### Done when

```bash
uv run python -m scripts.gen_keys
uv run python -m scripts.seed        # prints bootstrap credentials
uv run python -m scripts.seed        # second run changes nothing — proves idempotence
uv run provider                      # starts on :8000
curl localhost:8000/health           # {"database":"ok","redis":"ok"}
open http://localhost:8000/docs      # renders, health documented
```

Plus: `psql` shows every table, and the system scope rows are present with `is_system = true`.

*Tests arrived with Phase 1 — see the Testing section above. Phase 0's schema and seed are covered
indirectly by every integration test, which seeds through `scripts/seed.py`.*

---

## Phase 1 — AuthZ core

**Goal:** a working OIDC provider. A browser can complete authorization code + PKCE against the
seeded dashboard client and receive real tokens; a backend can complete client credentials. This is
the phase where the OAuth concepts actually get learned, so build the services before the routes.

### 1.1 Services first — `authz/services/`

| File | Responsibility |
|---|---|
| `pkce.py` | `verify_challenge(verifier, challenge, method)` — `S256` only; `plain` is rejected. ~10 lines. |

Write the RFC section into a comment wherever behaviour is non-obvious (PKCE: RFC 7636 Section 4.6;
redirect_uri matching: RFC 6749 Section 3.1.2.3; token error codes: RFC 6749 Section 5.2). Hand-rolling means the
spec is the reference, and a reader should not have to go looking for which rule a line enforces.
| `session_store.py` | Redis-backed login session: `sub`, `amr` list, `authenticated_at`, sliding 24h TTL. Keyed by an opaque id held in an `HttpOnly` `Secure` `SameSite=Lax` cookie. |
| `challenge_store.py` | Redis-backed 10-minute, single-use challenges carrying the pending `/authorize` parameters across the redirect to `auth-ui` and back. |
| `auth_methods.py` | The registry. Each method declares a name (`pwd`, `otp`, `face`) and a verify callable. `pwd` and `otp` register here; Phase 5 adds `face` **without touching this file's callers**. |
| `scope_resolver.py` | The centrepiece — see below. |
| `token_service.py` | Mint access/ID/refresh tokens, verify access tokens, denylist a `jti`, rotate a refresh token with reuse detection. |

**`scope_resolver.py`** — pure, synchronous set logic over data loaded by the caller:

```text
effective_user_scopes(user) =
      direct UserScope grants
    ∪ scopes of roles from UserRole
    ∪ scopes of roles from GroupRole for every group the user belongs to

authorization_code:  granted = requested ∩ client.grantable_scopes ∩ effective_user_scopes
client_credentials:  granted = requested ∩ client.granted_scopes
```

Pruning is silent — an over-broad request yields a narrower token, never an error. Load the whole
role/group graph in one query with eager loading; this runs on every token issuance and is the
obvious N+1 trap.

**`token_service.py`** — claims per [README.md — Tokens & Claims](README.md#tokens--claims). `acr` is derived from the
session's `amr` list at issuance time, never stored. Access tokens carry `aud` = the audience of the
API owning the granted scopes; if granted scopes span several APIs, `aud` is a list.

### 1.2 Discovery — `authz/discovery/`

| Endpoint | Notes |
|---|---|
| `GET /.well-known/openid-configuration` | Advertises endpoints, `grant_types_supported` = `authorization_code` + `client_credentials`, `code_challenge_methods_supported` = `["S256"]`, `acr_values_supported`, `scopes_supported` (**queried from the database**, since scopes are now dynamic), `claims_supported` including `acr` and `amr` |
| `GET /.well-known/jwks.json` | `core/crypto.jwks()` |

### 1.3 OAuth endpoints — `authz/oauth/`

| Endpoint | Behaviour |
|---|---|
| `GET /oauth2/authorize` | Validate `client_id`, exact-match `redirect_uri`, `response_type=code`, require `code_challenge` + `S256`. No session, or session below the requested `acr_values` → create a challenge and redirect to `auth-ui`. Session sufficient → resolve scopes, apply consent rules, issue the code, redirect back with `code` + `state`. |
| `POST /oauth2/token` | `grant_type=authorization_code` (verify code, single-use, PKCE, redirect_uri match → access + ID + refresh), `grant_type=refresh_token` (rotate, reuse detection), `grant_type=client_credentials` (client auth via `client_secret_basic` or `_post`). |
| `GET /oauth2/userinfo` | Bearer access token → claims filtered by the granted scopes (`openid`, `profile`, `email`). |
| `POST /oauth2/revoke` | RFC 7009. Revokes a refresh family, or denylists an access token's `jti`. |
| `POST /oauth2/introspect` | RFC 7662, client-authenticated. Present mainly so external non-JWT consumers have an option. |
| `GET /oauth2/logout` | RFC-style end-session: clear the session, honour `post_logout_redirect_uri`. |

Error responses follow the OAuth error format (`error`, `error_description`) — **not** the internal
error contract. Redirect-safe errors go back to `redirect_uri`; everything else renders as JSON.

### 1.4 Login & consent — `authz/login/`, `authz/consent/`

| Endpoint | Behaviour |
|---|---|
| `POST /api/v1/auth/login` | Verify email + password (argon2), append `pwd` to the session `amr`, return the next step (`totp_required`, `consent_required`, or the resume URL). |
| `POST /api/v1/auth/totp` | Verify a TOTP code (pyotp), append `otp`. Step-up: usable both during initial login and mid-session when a client requests a higher `acr`. |
| `POST /api/v1/auth/biometric` | Phase 5. The route exists here as a `501` stub when `iden_biometric_enabled` is false, so the Auth UI contract is fixed from the start. |
| `GET  /api/v1/auth/challenge/{id}` | The Auth UI reads the pending client name and requested scopes to render the page. |
| `POST /api/v1/auth/consent` | Persist a `ConsentGrant` (or deny) and resume `/authorize`. |

**Consent rules:** skipped entirely when `client.skip_consent` is true; otherwise skipped when an
existing `ConsentGrant` already covers every scope about to be granted; otherwise prompted, listing
each scope with its admin-written description — which is exactly why `Scope.description` is a
required field.

### 1.5 The `require_scope` dependency — `core/auth.py`

The single gate every resource-server route in Phases 2–4 depends on:

```python
async def require_scope(*required: str) -> ...:
    # extract bearer token → verify signature + exp + iss + aud via core.crypto
    # reject if jti is denylisted
    # reject if any required scope is missing from the token's scope claim
    # return the decoded token as CurrentTokenDep
```

Missing/invalid token → `401` with `WWW-Authenticate`. Valid token, insufficient scope → `403`. That
distinction matters: `401` means *authenticate again*, `403` means *authentication won't help*.

### Done when

You can complete a full flow by hand with `curl` plus a browser:

```bash
# 1. discovery lists both grants and S256 only
curl -s localhost:8000/.well-known/openid-configuration | jq

# 2. authorization code + PKCE, end to end
#    open /oauth2/authorize?... in a browser, log in as the bootstrap admin,
#    copy the code from the redirect, then:
curl -s -X POST localhost:8000/oauth2/token \
  -d grant_type=authorization_code -d code=… -d code_verifier=… \
  -d client_id=dashboard -d redirect_uri=…

# 3. decode the access token — aud, scope, acr, amr, jti all present
# 4. client credentials for the kiosk client returns a token with only its granted scopes
# 5. refresh once, then replay the old refresh token → the whole family is revoked
# 6. a token missing a required scope hits 403; a tampered token hits 401
```

Then, as the real check: `uv run pytest`. At the end of Phase 1 that was 124 tests — PKCE against
the RFC 7636 vector, acr derivation, the scope resolver, discovery, the full authorization code
flow, refresh rotation and reuse detection, client credentials, revocation, introspection, logout,
and `require_scope`. The suite grows with each phase; it stands at 398.

---

### Revisited: wrapping Authlib

Reopened after Phase 2 and closed again, so it does not get relitigated a third time:

- **Authlib is not OpenID-certified.** Certification is a paid conformance process; there are
  long-standing open requests ([#220](https://github.com/lepture/authlib/issues/220),
  [#250](https://github.com/lepture/authlib/issues/250)) and no Python server library appears on the
  [certified list](https://openid.net/certification/certified-openid-connect-implementations/).
  Certification attaches to deployments, not libraries.
- **Its provider core is sync-only.** Zero `async def` across all 13 modules of
  `authlib.oauth2.rfc6749`. `create_authorization_response`, `create_token_response`, and every hook
  you must implement — `query_client`, `save_token`, `query_authorization_code`,
  `save_authorization_code`, `authenticate_user` — are synchronous and every one of them needs the
  database. Wrapping it means a second synchronous engine plus a thread-pool bridge, and transactions
  that cannot span the boundary.
- **It would not supply the IDEN-specific parts anyway** — scope resolution, `acr`/`amr` derivation,
  audience computation, the consent and challenge flow. Those stay ours; they would just move into
  Authlib's hooks.
- **Still worth borrowing, if the hand-rolled error shapes ever prove wrong:**
  `authlib.oauth2.rfc6749.errors` and `authlib.oauth2.rfc7636` are pure, sync-safe, and need no
  adapter. (Its `create_s256_code_challenge` produces the same output as ours on the RFC 7636 vector.)
  Note `authlib.jose` is deprecated in favour of `joserfc`.

**Decision: stay hand-rolled**, and spend the effort on the known issues instead.

### Built differently than planned

Recorded so the code and this plan do not drift apart:

- **`RefreshToken` gained `acr` and `amr` columns.** A refreshed access token has to report the
  original authentication event, and nothing else remembers it.
- **Login never returns `consent_required`.** It returns `complete` or `totp_required`; consent is
  decided by `/authorize`, the only endpoint holding the full request. Fewer places know the rules.
- **`/oauth2/userinfo` does not use `require_scope`.** That helper derives an audience from the
  scope's prefix, which is meaningless for `openid`. Userinfo verifies the token itself and gates on
  the `openid` scope instead — OIDC Core Section 5.3.
- **CORS middleware moved up from Phase 6.** The Auth UI is a separate origin and sends the session
  cookie, so credentialed CORS is what makes login work at all rather than a hardening extra.
- **A token for the wrong API returns `401`, not `403`.** Audience is validated as part of the token,
  before any scope comparison. Worth knowing before it looks like a bug.

---

## Phase 2 — Admin RS (identity & access control)

**Goal:** the feature that makes IDEN an access-control provider. Every resource is a feature package
under `admin/` with `routes.py` / `schemas.py` / `service.py` / `errors.py`, and every route is gated
by `Depends(require_scope(...))`.

Build in dependency order — APIs and scopes first, since roles reference scopes and clients reference
both.

### 2.1 `admin/apis/` — `admin:apis:read` / `admin:apis:write`

`GET /admin/apis` · `POST /admin/apis` · `GET|PATCH|DELETE /admin/apis/{id}`

Audience must be a valid absolute URI and unique. `DELETE` on an `is_system` API → `409`. Deleting an
API cascades to its scopes, so the response spells out how many scopes and role bindings go with it.

### 2.2 `admin/scopes/` — `admin:scopes:read` / `admin:scopes:write`

`GET|POST /admin/apis/{api_id}/scopes` · `GET|PATCH|DELETE /admin/scopes/{id}`

Scope values are validated against a documented pattern (`^[a-z][a-z0-9_-]*(:[a-z0-9_-]+)+$`) and are
unique per API. `description` is required — it is what a user reads on the consent screen. System
scopes are immutable.

### 2.3 `admin/roles/` — `admin:roles:read` / `admin:roles:write`

`GET|POST /admin/roles` · `GET|PATCH|DELETE /admin/roles/{id}` ·
`GET /admin/roles/{id}/scopes` · `PUT /admin/roles/{id}/scopes`

`PUT` replaces the scope set wholesale with a list of scope ids — a declarative set operation rather
than add/remove pairs, which keeps the dashboard's editing UI trivial and the endpoint idempotent.
System roles cannot be deleted; their scope sets cannot be edited.

### 2.4 `admin/groups/` — `admin:groups:read` / `admin:groups:write`

`GET|POST /admin/groups` · `GET|PATCH|DELETE /admin/groups/{id}` ·
`PUT /admin/groups/{id}/roles` · `GET /admin/groups/{id}/members` ·
`POST|DELETE /admin/groups/{id}/members`

Membership is flat. Deleting a group removes its role bindings and memberships, never its users.

### 2.5 `admin/users/` — `admin:users:read` / `admin:users:write`

`GET|POST /admin/users` · `GET|PATCH|DELETE /admin/users/{id}` ·
`PUT /admin/users/{id}/roles` · `PUT /admin/users/{id}/scopes` (direct grants) ·
`POST /admin/users/{id}/reset-password` · `GET /admin/users/{id}/effective-scopes`

`GET /admin/users/{id}/effective-scopes` returns every scope **with its provenance** — direct grant,
which role, or which group. This is the endpoint that answers *why can this person do that?*, and
it is worth building carefully; it is also the natural place to reuse `scope_resolver.py` from
Phase 1 rather than reimplementing the union.

`GET /admin/users` supports filtering by group, role, and active status, and paginates.

### 2.6 `admin/clients/` — `admin:clients:read` / `admin:clients:write`

`GET|POST /admin/clients` · `GET|PATCH|DELETE /admin/clients/{id}` ·
`POST /admin/clients/{id}/rotate-secret` · `PUT /admin/clients/{id}/scopes`

Creating a confidential client returns the cleartext secret **exactly once**; it is argon2-hashed via
`core/security.py` and never retrievable again. `rotate-secret` behaves the same way. Public clients
get no secret and must use PKCE. `PUT .../scopes` sets both lists: *grantable* (may be requested on
behalf of a user) and *granted* (held by the client itself for `client_credentials`).

### Built differently than planned

- **Scope values are globally unique**, not unique per API. A token carries scopes as bare strings
  and the audience is resolved from the value, so two APIs defining `records:read` would put both
  their audiences into one token. Namespacing by API (`attendance:records:read`) is how collisions
  are avoided in practice.
- **Destructive deletes are guarded by `force=true`.** Deleting an API, scope, or role that is still
  granted silently strips permissions from whoever held them, so it returns `409` until the caller
  says explicitly that this is the intent.
- **Domain errors are mapped centrally**, by exception class, in `core/app.py` — `ApiNotFound` is a
  `NotFoundError`, so it lands on 404 without a per-route `try/except`. Thirty routes each repeating
  the same translation would be noise; routes still declare their failures in `responses={...}`.
- **Query parameters are camelCase-aliased** (`?groupId=`, `?isActive=`). FastAPI does not apply the
  Pydantic alias generator to query parameters, so without the alias a caller sending `groupId` gets
  an unfiltered list back — a plausible wrong answer, which is the worst kind.
- **Email validation is deliberately permissive** (`something@something`). A self-hosted IdP holds
  internal addresses like `admin@localhost`; `EmailStr` rejects those as special-use domains, which
  would make the bootstrap administrator un-creatable through IDEN's own API.
- **`session_store` gained a per-user index.** Sessions are keyed by a hash of a secret only the
  browser holds, so without it "revoke every session for this user" is unanswerable. Password reset
  and deactivation both need it, and Phase 4's `/entity/sessions` will too.
- **Deactivating a user revokes sessions and refresh tokens immediately**, rather than letting the
  account stay usable until they expire.

### Done when

A complete admin story runs against a live server using an admin access token from Phase 1:

```bash
# create an API, add a scope to it, bundle it into a role,
# create a group, give the group the role, add a user to the group,
# then confirm the user's effective-scopes includes the new scope with provenance,
# and confirm a fresh token for that user actually carries it.
```

Also verify: deleting a system scope returns `409`; a non-admin token returns `403` on every
`/admin/*` route; `/docs` shows required scopes on every endpoint.

Tests: `tests/test_access_control_story.py` runs exactly that story end to end — an admin defines a
permission for a backend IDEN has never heard of, routes it through a role and a group, and a token
comes out carrying it, with the right `aud`. Plus per-resource tests for authorization, validation,
system-row protection, and the guarded deletes.

---

## Phase 3 — SSO: session control and single sign-out

**Status: done.** 3.1 through 3.5 shipped; `tests/test_sso.py` and `tests/test_logout.py` pin them.
Two things came out differently from the plan below and are worth reading:

- **`sid` is a hash of the session id, not the id.** The plan said publishing the session id was safe
  because Redis keys on a hash of it. That was wrong: the id *is* the `iden_session` cookie, so every
  ID token would have handed its client — and anyone reading a token in transit — the ability to set
  that cookie and become the user. Caught while building 3.3, fixed in the commit after 3.1.
- **`auth_time` was wrong before this phase.** It came from the authorization code's `created_at`, so
  on the second application of an SSO session it reported when the code was minted rather than when
  the person authenticated, making every session look freshly authenticated to a client checking
  `max_age`. Codes and refresh tokens now carry the session's `authenticated_at`.

**Goal:** finish the single sign-on that Phase 1 half-built.

**Start by reading this, because the phase is easy to misread.** IDEN already does SSO. The
`iden_session` cookie is the mechanism: a user signs into app A through `/authorize`, and when app B
redirects to `/authorize` the session is found, `acr` is checked, consent is skipped if it was
already given, and a code comes straight back with no second password prompt. That works today for
every registered client.

What is missing is the other two thirds of the feature:

1. **The parameters a relying party uses to steer it.** Without `prompt=none` a browser app cannot
   ask "is this person still signed in?" without a full-page redirect, which is why it exists.
   Without `max_age` a bank-like client cannot demand a fresh login for a sensitive screen.
2. **Single sign-*out*.** `GET /oauth2/logout` clears IDEN's own cookie and nothing else. Every
   relying party keeps its own session, so the user is "signed out" and still signed in everywhere.
   An identity provider that cannot end the sessions it started is not finished.

Ordered before the Entity RS deliberately: `/entity/sessions` should be able to show *which
applications* a session is signed into, and that list only exists once this phase records it.

### 3.1 Session identity — `authz/services/session_store.py`

The `Session` already carries `authenticated_at`, which is what `auth_time` is minted from. Two
things are added:

| Addition | Why |
|---|---|
| `sid` in the ID token — the session id | The relying party needs a name for the session it is being told to end. It is the existing session id, not a new one. |
| `session_clients:{sid}` — a Redis set, same TTL as the session | Sign-out cannot notify the applications a session touched without recording which applications it touched. Written whenever a code is issued for a client. |

`sid` is safe to publish: session lookups key on a **hash** of the id, so knowing a `sid` does not
let anyone assume the session. That is the same reason it is safe to log.

### 3.2 `/authorize` parameters — `authz/oauth/routes.py`

| Parameter | Behaviour |
|---|---|
| `prompt=none` | Never show UI. If there is no session, the session fails `acr_values`/`max_age`, or consent is missing, redirect back with `login_required`, `interaction_required`, or `consent_required` (OIDC Core Section 3.1.2.6). **Must not create a challenge** — a challenge is interaction. |
| `prompt=login` | Force re-authentication even with a live session. Records a fresh `amr`/`authenticated_at`; the existing session is reused, not replaced, so other applications stay signed in. |
| `prompt=consent` | Ask again even when a consent grant exists. Does not delete the stored grant unless the user changes it. |
| `prompt=select_account` | Same as `login` for now, and documented as such: IDEN has no multi-account session. Recognised rather than rejected so conforming clients do not break. |
| `max_age` | Seconds. If `now - authenticated_at > max_age`, step up exactly as an unmet `acr_values` does today. Combined with `prompt=none`, a stale session is `login_required`. |
| `login_hint` | Passed through to the Auth UI to prefill the email. Never trusted as an assertion of identity. |
| `id_token_hint` | Which subject the client believes is signed in. If it disagrees with the session, treat as no session. |

`prompt=none` deserves care: it is the one path where an error is the *expected* outcome, and it must
be indistinguishable in timing and shape from any other refusal, or it becomes a probe for whether a
given browser has a session at IDEN.

### 3.3 Back-channel logout — `authz/logout/`

The substance of the phase. OIDC Back-Channel Logout 1.0.

`Client` gains `backchannel_logout_uri` and `backchannel_logout_session_required`. When a session
ends — via `/oauth2/logout`, an admin's "revoke everything", a password change, or a deactivation —
IDEN reads `session_clients:{sid}` and POSTs a **logout token** to each registered URI.

A logout token is a signed JWT that must not be mistakable for an ID token:

```json
{
  "iss": "…", "aud": "<client_id>", "iat": …, "jti": "…",
  "sub": "<user id>", "sid": "<session id>",
  "events": { "http://schemas.openid.net/event/backchannel-logout": {} }
}
```

The `events` claim is what makes it a logout token, and the **absence of `nonce`** is required —
without both rules a stolen logout token could be replayed as proof of authentication.

Delivery is best-effort with a short timeout, run concurrently, and every attempt is audited with its
outcome. Deliberately *not* retried into a queue: a relying party that was unreachable will
re-validate on its next token exchange anyway, and a durable job queue is a dependency this project
does not otherwise need. Record the failure and move on.

### 3.4 The end-session endpoint — `/oauth2/logout`

Already exists and already validates `post_logout_redirect_uri`. It gains `id_token_hint` (which
identifies the session and the client), `client_id`, and `state`, and it now triggers Section 3.3 before
clearing the cookie.

Deleting the session must happen **after** the fan-out is dispatched but must not wait on its
result; the user's redirect is not held up by a slow relying party.

### 3.5 Discovery and the admin surface

`end_session_endpoint`, `backchannel_logout_supported`, `backchannel_logout_session_supported`, and
`prompt_values_supported` in `/.well-known/openid-configuration` — a conforming client will not
attempt any of this without them. `admin/clients/` accepts and returns the two new columns.

**Done when:**

- A second application signs a user in with no prompt (already true — pin it with a test).
- `prompt=none` with a live session returns a code; with no session it returns `login_required` to
  the redirect URI and creates nothing in Redis.
- `max_age=0` forces a password prompt on an otherwise valid session.
- Signing out of one application delivers a logout token to every other application the session
  touched, and none to applications it did not — and revokes the refresh tokens that session
  produced, without touching another session's.
- A logout token has `events`, has no `nonce`, and is rejected by IDEN's own `verify_jwt` when
  presented as an ID token.
- The audit log shows the fan-out, one entry per relying party, including the failures.

---

## Phase 4 — Entity RS (self-service)

**Status: done.** 4.1 through 4.4 shipped; `tests/test_profile_fields.py`, `tests/test_entity.py`
and `tests/test_recovery.py` pin them. One thing the plan did not anticipate: `require_fresh_auth`
reads `auth_time`, and access tokens did not carry it — only ID tokens did. A resource server never
sees an ID token, so freshness was unenforceable until access tokens gained the claim (RFC 9068
Section 2.2.1).

**Goal:** what a signed-in person can do for themselves, plus the organization-defined profile
schema that makes IDEN usable by a university and a company without either one forking it.

**Before starting:** ~~KI-1~~, ~~KI-15~~ (Alembic) and ~~KI-12~~ (audit log) — all three grew more
expensive with every phase that passed, so all three were taken before Phase 3. This phase's new
tables arrive as migrations, and its write endpoints are audited by the middleware without touching
them. See [Known issues](#known-issues).

**The governing rule:** *a user may change anything about themselves that does not change what they
are allowed to do.* Authority is admin territory; everything else is theirs. Roles, groups, and
scopes are therefore absent from this module entirely.

Every route derives the user from the token's `sub` and never accepts a user id from the caller —
that alone removes an entire class of IDOR bugs.

### 4.1 Organization-defined profile fields

The feature that makes the Entity RS worth building. A university needs `student_id`, `department`,
`enrollment_year`; a company needs `employee_id`, `cost_centre`, `manager`. IDEN ships neither —
administrators define fields at runtime, exactly as they define scopes.

**`ProfileField`** (`admin/profile_fields/`, new scopes `admin:profile-fields:read|write`):

| Column | Purpose |
|---|---|
| `key` | `student_id` — stable identifier, referenced by claim mapping |
| `label`, `description` | What the form renders |
| `data_type` | `string` · `integer` · `boolean` · `date` · `enum` · `email` · `phone` · `url` |
| `options` | Allowed values when `data_type` is `enum` |
| `required`, `unique` | `unique` becomes a database constraint, not a service-layer check |
| `validators` | `pattern` / `min` / `max` / `min_length` / `max_length` |
| **`user_readable`, `user_writable`** | The pair that defines the self-service surface |
| `group_id` | Optional. Bound to a group, the field applies only to its members — how students and staff get different fields without a second grouping concept |
| `claim_name`, `claim_scope` | Optional token claim, released only when that scope was granted |
| `display_order`, `is_system` | Form ordering; `email`/`username`/`display_name` are built in |

**`UserProfileValue`** — one row per user per field, `UNIQUE (user_id, field_id)`, plus a partial
unique index on `(field_id, value)` for fields marked unique.

Why a values table rather than a JSONB column on `users`:

- **Uniqueness is a real constraint.** `student_id` must not collide. With JSONB that needs a
  partial unique index created *per field at runtime* — DDL triggered by an admin API call. A
  check-then-write in the service layer races under load.
- **Filtering works.** "Every user in Computer Science" is an indexed query, not a GIN scan.
- **Renaming a field is free.** Values reference `field_id`, so changing a key rewrites one row
  rather than every user's profile.

The cost is that values are stored as text with `data_type` driving the cast at the boundary, and
one extra query per profile read. Both are acceptable; the constraint story is not negotiable.
Keycloak's `USER_ATTRIBUTE` table is the same shape, for the same reasons.

**`user_writable` is what the self-service surface *means*.** `PATCH /entity/profile` does not have
a fixed field list — it accepts precisely the fields an admin marked writable. `student_id` is set
by the registrar through the admin API and is read-only to the student; `preferred_name` is theirs.
Same table, same endpoint, opposite permissions.

**Custom claims are opt-in.** A field is invisible to clients until someone sets `claim_name` and
`claim_scope`. Data minimization by default, and it reuses the Phase 2 scope system rather than
inventing a parallel release mechanism. Validate `claim_name` against the reserved OIDC claim names
so a custom field cannot shadow `sub`, `iss`, or `aud`.

### 4.2 Self-service endpoints

| Package | Endpoints | Scope |
|---|---|---|
| `entity/profile/` | `GET /entity/profile`, `PATCH /entity/profile`, `GET /entity/profile/schema` | `entity:profile:read` / `:write` |
| `entity/credentials/` | `POST /entity/credentials/password`, `POST /entity/credentials/email` (+ verification) | `entity:credentials:write` |
| `entity/totp/` | `POST /entity/totp/enroll`, `/confirm`, `GET`/`DELETE /entity/totp` | `entity:totp:read` / `:enroll` |
| `entity/sessions/` | `GET /entity/sessions`, `DELETE /entity/sessions/{id}` | `entity:sessions:read` / `:revoke` |
| `entity/connections/` | `GET /entity/connections`, `DELETE /entity/connections/{client_id}` | `entity:connections:read` / `:revoke` (new) |
| `entity/permissions/` | `GET /entity/permissions` | `entity:permissions:read` |

`GET /entity/profile/schema` returns the field definitions the user may see, so the dashboard renders
the form from data instead of hardcoding one organization's fields into a general-purpose IdP.

`/entity/connections` closes a Phase 1 gap: `ConsentGrant` rows are persisted but the user currently
has no way to see which applications hold access, or to withdraw it.

### 4.3 Freshness for sensitive operations

`require_fresh_auth(max_age=300)` in `core/auth.py`, checking the token's `auth_time`, applied to
password change, email change, TOTP removal, and session revocation.

A valid access token is not enough for these: an attacker holding a stolen token could otherwise take
over the account outright. Requiring a *recent* authentication forces them back through the login
they cannot complete. Returns `403` with `error="insufficient_user_authentication"` and the required
`max_age`, so the client knows to send the user through a re-auth rather than giving up.

### 4.4 Password reset

Belongs to the AuthZ module, not here: a locked-out user has no token, so no Entity RS route can
help them. Without it every forgotten password is an admin support ticket.

- `POST /api/v1/auth/password-reset` — always returns `202`, whether or not the email exists. A
  different response for unknown addresses turns this into an account-enumeration oracle.
- `POST /api/v1/auth/password-reset/confirm` — single-use token, 15-minute TTL, hashed in Redis.
  On success: revoke every refresh token and clear every session for that user.
- Delivery sits behind a small `notifier` interface that writes the link to the log in dev. Choosing
  an SMTP provider is a Phase 6 concern and should not block this.

### Other rules worth encoding

- A password or email change revokes every refresh token and clears the user's other sessions.
- TOTP enrollment is two-step — the credential activates only once a generated code is confirmed, so
  a mis-scanned QR code cannot lock someone out.
- `GET /entity/permissions` reuses `scope_resolver.scope_provenance()`. Three callers, one
  implementation.
- **Not offered:** account deletion. In a single-organization deployment the organization owns the
  identity — a student cannot delete their university account. Offer a deactivation *request* if the
  affordance is wanted.

### Done when

A non-admin user can sign in, read and update only the fields marked writable, and be rejected when
they try to write `student_id`. An admin defines a new field bound to the Students group, and it
appears in that user's `/entity/profile/schema` but not a staff member's. A field with
`claim_name` set shows up in the ID token only when its `claim_scope` was granted. Password change
requires a fresh authentication and invalidates the old refresh token. A forgotten password can be
recovered without an administrator.

Tests: per ground rule 8 — unit tests for field validation and the writability filter, integration
tests for the schema endpoint, the writability rejection, claim release, and freshness.

---

## Phase 5 — Biometric module

**Goal:** a face as a second factor, enrolled at a kiosk, shipped in-repo but **inert unless
enabled**.

**Status: done.** The engine (`engine/`), the provider module (`biometric/`, `entity/face/`, the face
step in `authz/login/`), the auth-ui face step and the dashboard's kiosk tickets shipped;
`tests/test_biometric.py` pins the provider side with a fake engine, `engine/tests/` the engine
against the real models. The kiosk app that captures faces is Phase 8. What a face is for, and what
it does not protect against, is [doc/concepts/biometrics.md](../doc/concepts/biometrics.md).

### What made this additive rather than invasive

| Seam | Built in | Used here |
|---|---|---|
| `iden_biometric_enabled` flag | Phase 0 | Read per request: the routes are mounted always, answer 404 while it is off, and are left out of `/docs`. The biometric API and face scopes are seeded only when it is on |
| `auth_methods.py` registry | Phase 1 | Registers `face`, enabled by the flag; discovery then advertises `urn:iden:acr:mfa-face` |
| `POST /api/v1/auth/biometric` stub | Phase 1 | The `501` stub became the handler; it still answers `501` with the flag off |
| `client_credentials` grant | Phase 1 | The kiosk authenticates as itself |

### Decisions

- **1:1 only.** Every comparison is against the face on the account that already signed in with a
  password. No 1:N search: an identity provider never asks *who is this?*, a search's false-match
  rate grows with every enrolment, its templates would have to sit unencrypted where an index can
  read them, and it is the biometric processing regulators treat most strictly. So no pgvector:
  the migration drops it, and embeddings are encrypted with the TOTP key and bound to their owner.
- **A second factor only.** The face endpoints need a session the password step created. A face is
  never a way in on its own.
- **Enrolment only at a kiosk, named by a ticket.** The kiosk's credential (`biometric:enroll`)
  names nobody. The person creates a single-use ticket in the dashboard after a fresh sign-in and
  shows it as a QR code; that is what says whose face it is. A stolen kiosk secret enrols no one.
  The person is emailed when a face is enrolled.
- **Liveness is four checks, each against a different attack.** Anti-spoofing models (prints,
  screens), two random head movements (photos, earlier recordings), four random screen colours the
  face must reflect (replays), one face throughout (swaps). The movements and colours are a
  single-use challenge per capture.
- **An enrolled face alone owes nothing.** An authenticator makes a second factor owed at every
  sign-in; a face answers that as well as a code, but does not create it — no camera must not mean
  no way in. A client asking for `mfa-face` is offered only the face.
- **The engine is stateless and holds the face maths.** The provider sends frames and, to verify,
  the decrypted templates; thresholds live beside each model in `engine/models.toml`, with a
  `version` stamped on every template so a model change never compares across models.
- **Photos kept only on request** (`IDEN_BIOMETRIC_KEEP_IMAGES`), encrypted, so
  `scripts.reembed_faces` can move faces to a new model.
- **Open research weights by default**, pinned by checksum; the recogniser's licence is
  non-commercial and the docs say so. CUDA when a GPU is present.

### Open

- **The threshold ships uncalibrated.** `engine/eval` measures it on a deployment's own cameras;
  nobody has run it on the production hardware yet.
- **The GPU image is unexercised.** It targets CUDA 12.9 / cuDNN 9 — held there because the
  deployment's GTX 1070 is Pascal, which CUDA 13 dropped — and has not yet been built or run on the
  host; the CPU image has.
- **No certified anti-spoofing.** The checks are not tested against ISO/IEC 30107-3 or CEN/TS 18099,
  and nothing server-side can prove a frame came from a real camera.

---

## Phase 6 — Hardening

**Goal:** the difference between "the flows work" and "this can be deployed".

- ~~**Migrations.**~~ Done ahead of Phase 3 — see [KI-15](#resolved). The reasoning for deferring
  them (the schema churns through Phases 0–3) turned out to argue the other way: the churn is
  exactly what produced three rounds of manual surgery on the dev database.
- ~~**Rate limiting.**~~ Done ahead of Phase 5 — see [KI-13](#resolved). It landed as per-route
  dependencies rather than the middleware planned here: a refusal then runs after routing and still
  reaches the audit log. `/biometric/*` still needs its own limits when it exists.
- ~~**Audit log.**~~ Done ahead of Phase 3 — see [KI-12](#resolved). It should not have been here:
  history not written is lost, so every phase this waited for was history nobody could recover.
- ~~**Security headers & CORS.**~~ Done. `core/headers.py`, one pure-ASGI middleware mounted
  outermost so the headers reach the responses the inner middleware produces on its own — a CORS
  preflight, an audit failure — not only the ones routes return. CORS was already restricted, since
  the Auth UI is a separate origin and credentialed CORS is what makes login work at all.
  - `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` everywhere.
  - **CSP** `default-src 'none'; frame-ancestors 'none'; base-uri 'none'`. The provider serves JSON,
    so nothing may load. `/docs` and `/redoc` get the same policy minus `default-src` — they pull
    Swagger and ReDoc from a CDN, and render no user data. `X-Frame-Options` is deliberately absent:
    `frame-ancestors` replaces it in every browser new enough to run an OIDC client, and two headers
    expressing one policy is one more place for them to disagree.
  - **HSTS in production only.** Sent from `http://localhost` it pins *every* project on localhost
    to HTTPS in the developer's browser, which is slow to discover and tedious to undo.
  - **`Cache-Control: no-store` (with the RFC 6749 Section 5.1 `Pragma: no-cache`) by default**, closing a
    gap open since Phase 1: token responses carried no cache directives at all. Discovery and JWKS
    are the exception at `public, max-age=300` — every resource server fetches the key set, and
    making it uncacheable would put IDEN in the path of every token validation. That age doubles as
    the rotation budget: a new `kid` is invisible for up to five minutes.
- ~~**Error contract.**~~ Done. The shape existed since Phase 0; what was missing was everything that
  did not go through it. The provider spoke three dialects: `code`/`message`/`details` from the
  domain-error handler, Starlette's `{"detail": "..."}` from every dependency that raises
  `HTTPException` — `require_scope`, the entity user lookup, login — and FastAPI's
  `{"detail": [ ... ]}` for a malformed body, where the same key holds a list. Two handlers in
  `core/app.py` now translate both, centrally, rather than replacing `HTTPException` at forty call
  sites: the raising code was right, only the serialization was inconsistent. `WWW-Authenticate` is
  preserved, because RFC 6750 and RFC 9470 put the machine-readable part of a 401 and a step-up
  there. A malformed request to `/oauth2/*` answers RFC 6749 `invalid_request` instead — a client
  library reading Section 5.2 has no way to read anything else.
- ~~**Test coverage review.**~~ Done. `pytest-cov` measures it; the config in `pyproject.toml` says
  why there is deliberately **no threshold** — a gate teaches people to write tests that touch lines
  rather than tests that check behaviour. The review found two gaps worth filling and one bug:
  - **`shared/profile.py` was at 60%** — pure validation logic, the kind ground rule 8 says gets unit
    tests, reached only indirectly through endpoint tests. `tests/test_profile_values.py` covers it
    directly: every field type, every validator, and the `min: 0` case a truthiness check would
    silently ignore.
  - **Failure injection found an undocumented failure mode.** With Redis or PostgreSQL unreachable,
    the exception escaped to the ASGI server, which answers a bare `Internal Server Error` as plain
    text — a fourth body shape, appearing for the first time at the exact moment an operator is
    trying to work out what broke. Now `503` in the contract's shape with `Retry-After`. Narrowly
    caught: `OperationalError` and `InterfaceError`, not `SQLAlchemyError`, so a malformed query
    stays a 500. Reporting a bug as an outage sends someone hunting a problem that is not happening.
  - The concurrency cases listed here were already done — `tests/test_concurrency.py` for redemption
    races and `TestConcurrentRefresh` for two simultaneous refreshes of one token.

  93% of statements, 388 tests.
- ~~**Docker.**~~ Done. A two-stage `provider/Dockerfile`: dependencies resolve in a `uv` image and
  are copied forward, so the runtime image carries no uv, no build tools, and no lockfile, and runs
  as uid 1000 rather than root. Its `HEALTHCHECK` calls `/health/live` — readiness is the
  orchestrator's, since Compose has no way to drain traffic and checking dependencies there would
  only kill the container that reported them.

  `deploy/docker-compose.yml` gains `migrate` and `provider`. Migrations run as a **separate service
  that exits**, with `provider` waiting on `service_completed_successfully` — not an entrypoint step,
  because scaling the provider to two replicas would then run the migrations twice, concurrently,
  against one database.

  Two things are deliberately not here. **nginx**, because certificates are site-specific and the
  proxy is where flood protection belongs — it is the operator's, and the deployment guide says so.
  **MinIO**, because it exists for the biometric module, which is not built. Also fixed on the way
  through: `main()` hard-coded `reload=True`, which in a container is a memory cost and a restart
  loop waiting for a mounted file to change. It follows `IDEN_ENV` now.
- ~~**Operational endpoints.**~~ Done. `/health/live` answers `200` whenever the process can answer
  at all and touches no dependency; `/health/ready` checks PostgreSQL and Redis and answers `503`
  when either is unreachable, so a load balancer drains the replica without parsing a body. The split
  is the point: a liveness probe that checks the database restarts every replica the moment the
  database has a bad minute, turning a recoverable outage into a restart loop. `/health` stays as it
  was — always `200`, detail in the body — for a human who wants to know *why*.

- **Expired codes and tokens are deleted.** `scripts/cleanup.py`, run from cron or a scheduler, with
  `--dry-run` to see what it would remove first. Closes [KI-14](#operational-gaps). Only rows past
  `expires_at` plus an hour's margin: reuse detection works by finding the spent row and revoking its
  family, so deleting a revoked-but-unexpired token would turn a detectable theft into an ordinary
  `invalid_grant`. `audit_events` is deliberately untouched — a retention policy for who-did-what is
  an organizational decision, not a maintenance one.

### Done when

`docker compose -f deploy/docker-compose.yml up --build` brings up a working deployment —
verified: migrations ran to completion, the container reported healthy as uid `iden`, and
`/health/ready` answered `{"status":"ok"}` with the security headers attached. The suite passes at
388 tests, and the OWASP-relevant checks — rate limits engaged, no secrets in logs, headers present —
all hold.

---

## Session provenance — last seen, device, address

**Status: built.** `shared/user_agent.py`, the three fields on `session_store.Session`, and the
four new fields on `SessionSummary`. Pinned by `tests/test_session_store.py` and
`tests/test_user_agent.py`; three of the store tests fail without the change.

**Goal:** make `GET /entity/sessions` answer the question the screen actually asks — *is this one
mine?* Today it returns `authenticatedAt`, `amr`, and `clients`, which distinguishes sessions by how
and when they were created but not by **where from** or **whether still in use**. A person looking
for the session they do not recognise has nothing to recognise it by.

Everything here lives in Redis alongside the session. No migration, no new table: a session is
ephemeral, and this is a property of one.

### S.1 What a session records — `authz/services/session_store.py`

The `Session` dataclass and its JSON payload gain three fields:

| Field | Type | Written | Notes |
|---|---|---|---|
| `last_seen_at` | `datetime` | On read, throttled — see S.3 | Initialised to `authenticated_at` at creation. |
| `ip` | `str \| None` | At creation and at re-authentication | The socket peer. `None` when the peer is unknown. |
| `user_agent` | `str \| None` | At creation and at re-authentication | The raw header, stored as sent. |

**All three must be optional on read.** A deployment upgrading in place has live sessions whose
payload predates this change, and `json.loads` on the old shape must not raise. Read them with
`data.get(...)`, defaulting `last_seen_at` to `authenticated_at`. Getting this wrong signs out
everyone who was signed in at deploy time, which is the kind of upgrade people remember.

Re-authentication (`reauthenticate`) refreshes all three: it is a new sign-in on the same session id,
and the whole point of keeping the id is that the *session* continues — but the person may well be on
a different machine.

### S.2 Where the values come from — `authz/login/routes.py`

`session_store.create` currently takes `(redis, user_id, method)`. It gains keyword arguments:

```python
async def create(
    redis: Redis,
    user_id: UUID,
    method: str,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> Session: ...
```

The login route already has `Request`. Reuse `ratelimit.client_ip(request)` rather than reading
`X-Forwarded-For` — the same rule the audit log and the rate limiter already follow, and for the same
reason: a header the caller sets is a claim, not an observation. Trusting it here would let anyone
write whatever address they liked into their own session list, which is a strange thing to be able to
do to a security screen.

The honest consequence, and it belongs in the docs rather than being discovered: **behind a reverse
proxy every session reads as the proxy's address.** Making that useful is one decision — trusting
`X-Forwarded-For` from a configured set of proxy addresses — and it should be taken once, for the
audit log, the rate limiter, and this, not three times separately. Out of scope here; noted so it is
not silently wrong.

### S.3 The write-amplification problem

`session_store.get` runs on **every** request that carries the cookie — `/authorize`, every login
step, consent, logout. Writing `last_seen_at` on each one turns every session read into a session
write, which is a real cost for a field whose entire purpose is to be shown to a human, rounded to
the minute.

Throttle it: re-save only when the stored value is older than `SEEN_RESOLUTION` (60s).

```python
if (now - session.last_seen_at).total_seconds() > SEEN_RESOLUTION:
    session.last_seen_at = now
    await _save(redis, session)
```

The sliding `expire` stays unconditional — that one is correctness, not display. The cost of the
throttle is that "last active" can be up to a minute stale, which is invisible at the granularity
the screen renders ("3 hrs ago").

### S.4 Turning a user-agent into something readable

Store the header raw; derive the label for display. A new pure module, `shared/user_agent.py`:

```python
def describe(raw: str | None) -> tuple[str | None, str | None]:
    """(device_label, browser_label) — best effort, e.g. ("Mac · macOS", "Chrome 142")."""
```

An ordered list of `(pattern, label)` pairs and a version capture. Roughly thirty lines, no
dependency, and testable without a database — which is where the value is.

Three things to be deliberate about:

- **No library.** `ua-parser` and friends carry a regex database that goes stale, and updating it
  becomes a reason to redeploy the provider. A short list that degrades to `None` is better than a
  long one that is confidently wrong.
- **Best effort is the contract.** Every field is nullable and the UI must render without them. A
  browser IDEN has never heard of shows as an unnamed session, not as a broken row.
- **The raw string is already kept.** `AuditEvent.user_agent` records it per request, so nothing is
  lost by storing only labels for display. Do not add the raw header to the API response — it is
  fingerprinting material and the labels are what the screen needs.

Client Hints (`Sec-CH-UA-*`) are the modern replacement for UA sniffing and would be more accurate,
but they require opting in with `Accept-CH` and are not sent cross-origin by default. Worth revisiting
if the labels prove poor; not worth the protocol surface first time through.

### S.5 The API — `entity/sessions/schemas.py`

`SessionSummary` gains four nullable fields:

```python
last_seen_at: datetime = Field(description="When this session last made a request.")
ip: str | None = Field(
    default=None, description="Address the session was created from."
)
device_label: str | None = Field(
    default=None, description='Best effort, e.g. "Mac · macOS".'
)
browser_label: str | None = Field(
    default=None, description='Best effort, e.g. "Chrome 142".'
)
```

`last_seen_at` is non-null because a session always has one, even if it equals `authenticatedAt`.
`list_for_user` keeps sorting by `authenticated_at` — the order is *when this sign-in began*, which
is the stable thing; sorting by activity would make the list jump around while it is being read.

Then `pnpm gen:api` from `web/`, and commit the regenerated `schema.d.ts`.

### Deliberately not in scope

**Geolocation.** The mockup this came from shows "Bangkok, TH" beside each address, and that is the
one item here with a real dependency behind it: either a MaxMind database shipped and updated with
the deployment, or a third-party lookup, which means sending a person's address to someone else on
every render of their own security page. Show the address; let the person recognise it. Revisit as a
deployment-optional enrichment if it is genuinely wanted.

### Testing

| Test | Why |
|---|---|
| A session created without the new arguments still lists | The signature stays back-compatible. |
| A payload written in the old shape loads and lists | The upgrade case. Write the old JSON into Redis directly rather than constructing it through `create`, or the test proves nothing. |
| `get` twice inside `SEEN_RESOLUTION` writes once | The throttle. Fails without it — count `SET` calls. |
| `get` after `SEEN_RESOLUTION` advances `last_seen_at` | The other half; freeze time rather than sleeping. |
| `reauthenticate` replaces address and agent | A new sign-in on a kept id. |
| `describe()` unit cases, including an unknown agent → `(None, None)` | No database, no fixtures. |

### Done when

```bash
uv run pytest
curl -H "Authorization: Bearer $TOKEN" localhost:8000/entity/sessions | jq '.sessions[0]'
```

returns `lastSeenAt`, `ip`, `deviceLabel` and `browserLabel`; a second call a minute later shows
`lastSeenAt` advanced; and a session that predates the change appears in the list with the new fields
null rather than causing a `500`.

---

## Known issues

Found in a review after Phase 2, and reanalysed after the fix pass. Recorded here so they are
scheduled rather than remembered.

**Status** is *verified* (reproduced against the running app), *suspected* (reasoned from the code,
not yet demonstrated), or *resolved*. Fix the verified ones on evidence; demonstrate the suspected
ones with a failing test first — see ground rule 9.

### Resolved

| | Issue | What changed | Pinned by |
|---|---|---|---|
| **KI-1** | Introspection leaked token contents to unauthenticated callers | `/oauth2/introspect` now requires a **confidential** client via `authenticate_endpoint_client(..., require_confidential=True)`. `/oauth2/revoke` still admits public clients — RFC 7009 Section 2.1 allows it, the caller must already hold the token, and the existing owner check stops one client revoking another's. | `test_token_grants.py::TestIntrospection::test_public_client_cannot_introspect`, `::test_one_client_cannot_revoke_another_clients_token` |
| **KI-2** | Narrowing a refresh token's scope was permanent | `RefreshToken.scope` now always holds the **original grant**; a `scope` parameter narrows that one response without shrinking the grant. Re-resolution against current permissions is unchanged. | `::test_scope_narrowing_applies_to_one_response_only` |
| **KI-3** | Single-use enforcement was check-then-write | `consume_code` and `consume_refresh_token` take a row lock (`.with_for_update()`), so a second caller blocks until the first commits and then sees the burnt row. | `tests/test_concurrency.py` — both tests hold the first transaction open and assert the second blocks; both were confirmed to fail without the lock |
| **KI-4** | Consent recorded requested scopes, not granted ones | The consent route resolves the request first and stores what was actually granted, so a scope pruned for lack of permission is not silently pre-consented. | `test_consent.py::test_consent_records_what_was_granted_not_what_was_asked` |
| **KI-5** | `IndexError` on a client with no grants | The management endpoints no longer touch `allowed_grants` at all — they are not a grant. | `::test_client_with_no_grants_does_not_crash` |
| **KI-6** | `GET /admin/groups` was N+1 | One grouped `member_counts` query for the whole page. | `test_admin_users_groups.py::TestGroupListingCost` — asserts query count does not grow with row count |
| **KI-12** | No audit log | `audit_events`, written by pure-ASGI middleware in `core/audit.py` for every state-changing request — `/admin/*`, `/entity/*`, `/api/v1/auth/*`, `/oauth2/revoke` and `GET /oauth2/logout`. Records actor, route template, target, status, IP, and the request body with secrets redacted. `actor_user_id` is `ON DELETE SET NULL` with the actor's email kept alongside, so deleting a user cannot erase what they did. Readable at `GET /admin/audit` under the new `admin:audit:read` scope; there is no write endpoint. | `tests/test_audit.py` — 14 tests, including that reads are not recorded, that refused attempts are, that a password never reaches the row, and that history survives the actor's deletion |
| **KI-16** | Two honest simultaneous refreshes revoked the family | Both options from the writeup turned out to be needed, not either. A **replay window** (`IDEN_REFRESH_GRACE_PERIOD`, 30s) returns what a spent token was already exchanged for, to the same client only, with `expires_in` recomputed. A **Redis lock on the token** wraps the exchange, because the window alone only helps a caller arriving after the first finished — two requests in the same instant both find no replay and both rotate. Detection is delayed by one rotation, never removed: both parties end up holding the same next token, which collides outside the window. | `test_token_grants.py::TestConcurrentRefresh` — six tests; four fail without the window, and the `asyncio.gather` one fails without the lock (reliably under full-suite load, which is how the gap was found) |
| **KI-13** | No rate limiting | Two counters, because there are two attacks: **per address** on login, TOTP, `/oauth2/token` and password reset, and **per account, failures only** on login and TOTP. Failures rather than attempts, because counting every attempt against one account hands anyone a way to lock its owner out — clearing on success means whoever knows the password can still sign in. Per-route dependencies rather than middleware, so a refusal runs after routing and still reaches the audit log. A global flood cap belongs in the reverse proxy. | `tests/test_rate_limit.py` — seven tests; three fail without the limiter, including the one asserting the 429 is audited |
| **KI-8** | Nothing prevented locking yourself out | `admin/lockout.py`, called as a **post-condition** from the nine mutations that can remove authority. Every one asks the same question after the change and before the commit — *can anyone still administer this?* — which is one rule to get right instead of nine, answered against the world the commit would create rather than a prediction of it. The count is of active users holding **`admin:users:write`**, whatever the route: a direct grant, a role, or a role held by a group. That scope rather than the `administrator` role, because it is the one that can restore every other one — whoever holds it can set anyone's roles, including their own. Refusal is a `409`; the session rolls back, so a refused change lands nowhere. | `tests/test_lockout.py` — ten tests; eight fail without the guard. The two that do not are the ones asserting it does **not** over-fire, which is the other half of being right |
| **KI-15** | No migrations; `create_all` was the only way to build the schema | Alembic, with the initial revision generated from the settled Phase 2 models. `scripts/seed.py` no longer creates anything structural, and the test database is built by running the migrations — the same path a deployment takes, so there is only one way to produce a schema. | `tests/test_migrations.py` — autogenerate must find nothing left to do; confirmed to fail when a column is added to a model without a revision |

A correction to the earlier writeup of **KI-2**: the old test was *under-specified*, not wrong. It
checked that narrowing narrowed and that widening beyond the grant was refused — it simply never
checked whether the original scope could be recovered. It has been split into two tests that now
cover both.

### Open — correctness and security

**KI-17 · An audit row is not atomic with the change it describes.** The entry is written after the
response, from a session of its own, because by then the request's own transaction has already
committed. If the database becomes unreachable in between, the change stands and the record is lost.
The failure is logged at `error` rather than swallowed, so the gap is visible, but it is a gap.
*Options:* write the row inside the request's transaction — which means plumbing the actor through
every service and giving up the single middleware — or accept the window and monitor the error.
Low likelihood, high consequence: worth deciding before an audit actually matters.

### Design calls to ratify or overturn

These are working as written. They are listed because they were decided by default rather than
deliberately, and each has a real cost.

**KI-7 · `admin:roles:write` is effectively root.** Anyone holding it can add `admin:*` to a role
they hold. Reasonable for a single-org IdP, but it means "an admin who can only manage groups" is not
expressible. Expressing it needs a rule such as *you may not grant a scope you do not hold*.

**KI-9 · One token may carry several audiences.** Requesting admin and entity scopes yields both in
`aud`. Standard per RFC 9068, but a compromised resource server can replay the token at the other.
RFC 8707 (`resource`) is the tighter design if that matters.

~~**KI-10 · `require_scope` derives the audience from the scope prefix.**~~ **Resolved.**
`_audience_for` now derives only for the three prefixes IDEN registers itself and raises for
anything else, and `require_scope` takes an explicit `audience=` for routes outside the convention.
The raise happens when the router is built rather than per request, so what used to be a silent 401
on every call is now a startup failure naming the scope. Pinned by
`tests/test_conformance.py::TestDerivedAudience`.

**KI-11 · Key rotation needs a restart.** `core/crypto._keys` is `@cache`d at import. The docs called
rotation "a config change"; it is a config change *and* a rolling restart. **Resolved in Phase 6 by
correcting the documentation rather than the code**: re-reading keys on a timer buys nothing a
rolling restart does not already give, and adds a state where half the workers sign with the old key.
The five-minute `Cache-Control` on JWKS is the other half of the story — a resource server will not
see a new `kid` until its copy expires, so the restart has to lead the retirement of the old key by
at least that long.

### Operational gaps

~~**KI-14 · Expired authorization codes and refresh tokens are never deleted.**~~ Resolved in Phase 6
by `scripts/cleanup.py` — see the Phase 6 entry. Pinned by `tests/test_hardening.py::TestCleanup`,
including the case that matters most: a revoked token is kept until it expires, because reuse
detection needs the row.


### Suggested order

1. ~~KI-1~~ — with KI-2 through KI-6.
2. ~~KI-15~~ Alembic, ~~KI-12~~ audit log — both taken ahead of Phase 3.
3. ~~KI-13~~ — per-address and per-account limits, with a proxy expected to cap floods.
4. ~~KI-16~~ — the replay window and the lock, together.
5. ~~KI-8~~ — the last-administrator guard. **KI-7** still waits on what a non-root administrator
   should be.
6. ~~KI-14~~ and ~~KI-11~~ (as a documentation fix) with Phase 6 hardening.
7. ~~KI-10~~ with the conformance pass, which closed all eight Tier 1 gaps from the
   [README](../README.md#tier-1--conformance-gaps--closed) and adopted RFC 8414, RFC 9207,
   RFC 7662 Section 4 and RFC 7009 Section 2.1. **KI-9** remains open and deliberately so — see below.

**Deferred deliberately, before Phase 6.** None of the seven open issues blocks a later phase, so
they were reviewed and left standing rather than fixed first. What that decision rests on:

- **KI-7, KI-9, KI-17** are trade-offs, not defects. Each has a fix with a real cost — a partial-admin
  permission model, per-audience tokens, an actor plumbed through every service — and each protects
  against something a single-organization deployment does not yet face. They stay recorded so the
  cost is a choice rather than a surprise.
- ~~**KI-8**~~ was the one with a one-way door behind it, and was taken straight after Phase 6 for
  exactly that reason.
- ~~**KI-10**~~ was latent rather than harmless, and cost one guard clause to close. Taken with the
  conformance pass, because the same pass made `require_scope` grow an `audience` argument anyway.
- ~~**KI-11, KI-14**~~ were deployment concerns and were answered inside Phase 6 — rotation as a
  documentation correction, cleanup as `scripts/cleanup.py`.

That leaves **three** open, all by choice: KI-7, KI-9, KI-17.

---

## Why this order

The dependency between phases is not arbitrary, and it is worth understanding before deviating:

1. **Foundation first** because models, hashing, and signing keys underpin everything else.
2. **AuthZ before Admin**, even though the admin API is the more interesting feature. Every
   `/admin/*` route is gated by `require_scope`, which needs real tokens to exist — building admin
   first would mean testing it with a fake auth shim you then throw away. The seed script creates
   the clients and the admin user that Phase 1 needs, so nothing is circular.
3. **Admin before Entity** because Entity reuses `scope_resolver.py` and the same feature-package
   patterns, and because you need to be able to create a second, non-admin user to test Entity
   properly.
4. **Biometric after the core** because it is the only phase with an external dependency (the ONNX
   engine), and because everything it hooks into — the auth-method registry, the flag, the stub
   route, the `amr` pipeline — already exists by then.
5. **Hardening last** for migrations specifically: Alembic against a schema that is still moving
   costs more than it saves.

Phases 7 (frontends) and 8 (kiosk) from the root [README](../README.md) consume this backend and are
planned separately — the frontends in [web/PLAN.md](../web/PLAN.md).
