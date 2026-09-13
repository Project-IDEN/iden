# IDEN Provider

The IDEN backend: a single FastAPI application that is simultaneously an **OpenID Connect provider**
and an **access-control service**. This document is the reference — setup, configuration, data model,
endpoints, tokens, and conventions. For the *order of work*, see [PLAN.md](PLAN.md). For the
system-level picture (Docker topology, frontends, kiosks), see the [root README](../README.md). For the
reader-facing documentation — concepts, integration guides, operations — see
[`doc/`](../doc/index.md), which builds as a MkDocs site.

One process hosts four logical modules:

| Module | Prefix | What it does |
|---|---|---|
| **AuthZ Server** | `/.well-known/*`, `/oauth2/*`, `/api/v1/auth/*` | Issues tokens. Owns login, consent, sessions, and the OIDC protocol surface. |
| **Admin RS** | `/admin/*` | Manages users, groups, roles, APIs, scopes, and clients. |
| **Entity RS** | `/entity/*` | Self-service for the signed-in person. |
| **Biometric RS** | `/biometric/*` | Face enrollment and verification. Mounted only when enabled. |

They are **logical** modules, not services: one port, one image, one deployable. Because they share a
process, the resource-server modules verify access tokens in-process against the same keys the AuthZ
module signed them with — no introspection hop. Resource servers *outside* this repository get the
same guarantee by validating against the published JWKS.

---

## Table of Contents

- [Local Development](#local-development)
- [Configuration](#configuration)
- [Package Layout](#package-layout)
- [Data Model](#data-model)
- [Access Control in Practice](#access-control-in-practice)
- [The Audit Log](#the-audit-log)
- [Rate Limiting](#rate-limiting)
- [Organization-Defined Profiles](#organization-defined-profiles)
- [Refresh Rotation and the Grace Window](#refresh-rotation-and-the-grace-window)
- [Single Sign-On and Sign-Out](#single-sign-on-and-sign-out)
- [Endpoint Reference](#endpoint-reference)
- [Tokens & Claims](#tokens--claims)
- [Request Lifecycle](#request-lifecycle)
- [Conventions](#conventions)
- [Troubleshooting](#troubleshooting)

---

## Local Development

Python 3.14+, managed by [uv](https://docs.astral.sh/uv/), plus PostgreSQL with `pgvector` and Redis:

```bash
docker compose -f deploy/docker-compose.yml up -d    # postgres:18 + pgvector, redis:8
```

Then, from the repository root:

```bash
cd provider
uv sync                              # install dependencies into .venv
cp .env.example .env                 # then fill it in

uv run python -m scripts.gen_keys    # RSA signing keypair for local dev
uv run alembic upgrade head          # pgvector extension + every table
uv run python -m scripts.seed        # system catalogue, bootstrap admin and clients

uv run provider                      # uvicorn on :8000, reload enabled
```

Then:

- Interactive API docs — <http://localhost:8000/docs>
- Discovery — <http://localhost:8000/.well-known/openid-configuration>
- Health — <http://localhost:8000/health>

### Starting over

When development has left the database in a state not worth reasoning about:

```bash
uv run python -m scripts.reset         # asks before it does anything
uv run python -m scripts.reset --yes   # for when you are sure
```

It drops the schema, flushes Redis, migrates, and seeds — printing a new bootstrap password and
kiosk secret, because those are created fresh with everything else. Redis is the step people miss
doing this by hand: sessions outlive the rows they name, so a database-only reset leaves live
cookies pointing at users who no longer exist. It refuses outright when `IDEN_ENV=prod`.

### Running it in a container

The same stack, with the provider built and wired in rather than run from your shell:

```bash
uv run python -m scripts.gen_keys                              # once; mounted read-only
docker compose -f deploy/docker-compose.yml up --build
```

`migrate` runs `alembic upgrade head` and exits; `provider` waits for it to finish, then starts on
`:8000`. Migrations are a separate service rather than an entrypoint step on purpose — scale
`provider` to two replicas with migrations in the entrypoint and they run twice, at the same time,
against one database.

The image is two-stage: dependencies resolve in a `uv` image and are copied into a plain
`python:3.14-slim`, so what ships carries no uv, no build tools, and no lockfile, and runs as uid
1000. Its `HEALTHCHECK` calls `/health/live`, never `/health/ready` — see the note under those
endpoints for why.

TLS and a reverse proxy are not in this file: both are site-specific and belong to whoever operates
the deployment.

### Housekeeping

Authorization codes and refresh tokens are not deleted when they expire, so both tables grow for the
life of the deployment. Run this from cron, a Kubernetes `CronJob`, or a systemd timer:

```bash
uv run python -m scripts.cleanup --dry-run   # count what would go
uv run python -m scripts.cleanup             # delete it
```

It removes only rows past `expiresAt` plus an hour's margin. A revoked token that has not yet expired
is kept deliberately: reuse detection works by finding the spent row and revoking its family, so
deleting it early would turn a detectable theft into an ordinary `invalid_grant`. `audit_events` is
never touched — how long to keep a record of who did what is your organization's decision.

**Adding a dependency:** `uv add <package>` from `provider/`. Never hand-edit the `pyproject.toml`
dependency list — `uv` owns it and the lockfile.

**Running the tests:**

```bash
uv run pytest                             # 398 tests, ~30s
uv run pytest tests/test_scope_resolver.py -q
```

They use their own `iden_test` database (created and dropped per run) and Redis logical database 15,
so they never touch your development data. The app is driven in-process over ASGI — no server to
start. See [PLAN.md — Testing](PLAN.md#testing) for how the fixtures work.

**Coverage**, when you want to know what is not exercised:

```bash
uv run pytest --cov=provider --cov-report=term-missing
```

There is deliberately no threshold. Coverage here is a tool for finding gaps worth filling, not a
gate — a build that fails below a number teaches people to write tests that touch lines rather than
tests that check behaviour. It currently sits at 93%.

**The three checks**, all expected to be clean before a commit:

```bash
uv run ruff format .    # formatting, 88 columns
uv run ruff check .     # lint: E, F, I, UP, B
uv run pyright          # types, `standard` mode
```

`E501` and `B008` are switched off in `pyproject.toml`, each with the reason next to it: the
formatter already owns line length, and `Depends(require_scope(...))` in a parameter default is the
FastAPI idiom rather than the mutable default B008 is looking for.

`typeCheckingMode` is pinned to `standard` in the same file so an editor set to `strict` agrees with
what runs here. Strict is not a useful bar for a pytest suite — fixtures arrive as unannotated
parameters, and each unknown type cascades through every use of it, which produces about two thousand
findings that say nothing about the tests.

**Run them automatically.** The first three are wired to a git hook, once per clone:

```bash
uv run --project provider pre-commit install    # from the repository root
```

After that every `git commit` reformats, lints, and type-checks the staged Python before the commit
is written, along with a few file hygiene checks (merge-conflict markers, TOML/YAML syntax, trailing
whitespace, oversized files). Unstaged work is stashed first, so what is checked is exactly what is
being committed. A hook that rewrites a file fails the commit — `git add` the result and commit
again.

`uv run pytest` is deliberately **not** in the hook. It needs PostgreSQL and Redis running and takes
about thirteen seconds; a gate that fails because Docker is down teaches people to reach for
`--no-verify`, and a hook everyone bypasses is worse than no hook. Run the suite yourself, or add it
as a pre-push hook: `pre-commit install --hook-type pre-push`.

The hook is scoped to `provider/` — the only package with lint and type configuration so far. Widen
`files:` in `.pre-commit-config.yaml` when `kiosk/server` grows past a skeleton.

**After changing a model:**

```bash
uv run alembic revision --autogenerate -m "what changed"   # then read it
uv run alembic upgrade head
```

Read what autogenerate produced before applying it. It is reliable for added tables and columns, and
unreliable for anything it has to infer — a renamed column looks like a drop plus an add, and losing
the data in it is silent. Server defaults and `CHECK` constraints are often missed entirely.

`tests/test_migrations.py` fails if the models and the migrations disagree, so a forgotten revision
surfaces in the suite rather than at deployment. The test database is built by running the
migrations, which is the same path a deployment takes.

If your development database predates Alembic, it already has the Phase 2 tables — record that fact
rather than rebuilding it, then apply everything added since:

```bash
uv run alembic stamp 582ce19a8898    # the initial revision; those tables already exist
uv run alembic upgrade head          # audit_events and anything after it
uv run python -m scripts.seed        # pick up newly catalogued scopes
```

Stamping `head` instead would claim every revision is applied and leave the tables they create
missing.

The seed is still idempotent and still safe to re-run; it just no longer creates anything structural.

The seed prints the bootstrap administrator's password and the kiosk client's secret **once**. They
are argon2-hashed on the way into the database and cannot be recovered afterwards — losing them means
re-seeding into a fresh database.

---

## Configuration

All settings are environment variables prefixed `IDEN_`, loaded by `core/config.py` via
`pydantic-settings` from the process environment or `.env`.

### Application

| Variable | Default | Purpose |
|---|---|---|
| `IDEN_ENV` | `dev` | `dev` or `prod`. Selects console vs JSON log rendering. |
| `IDEN_LOG_LEVEL` | `info` | Root log level. |
| `IDEN_API_PREFIX` | *(empty)* | Optional prefix applied to every mounted router. |
| `IDEN_ALLOWED_ADMIN_ORIGINS` | `[]` | CORS allow-list for the dashboard SPA. |

### Issuer & UI

| Variable | Example | Purpose |
|---|---|---|
| `IDEN_ISSUER` | `http://localhost:8000` | The `iss` claim and the base for every advertised endpoint and system audience. Must match exactly what clients use, or signature validation succeeds and issuer validation fails. |
| `IDEN_AUTH_UI_BASE_URL` | `http://localhost:4000` | Where `/oauth2/authorize` redirects for login and consent. |

### Storage

| Variable | Example |
|---|---|
| `IDEN_DATABASE_URL` | `postgresql+asyncpg://iden:iden@localhost:5432/iden` |
| `IDEN_REDIS_URL` | `redis://localhost:6379/0` |

### Crypto

| Variable | Default | Purpose |
|---|---|---|
| `IDEN_SIGNING_KEY_DIR` | `./keys` | Directory of PEM keypairs. Each file's stem becomes its `kid`, which is what makes rotation a config change rather than a rewrite. |
| `IDEN_SIGNING_ALGORITHM` | `RS256` | JWT signing algorithm. |

### Lifetimes

| Variable | Default | Notes |
|---|---|---|
| `IDEN_ACCESS_TOKEN_TTL` | `600` (10 min) | Short on purpose — permission changes take effect at the next issuance. |
| `IDEN_ID_TOKEN_TTL` | `600` | |
| `IDEN_REFRESH_TOKEN_TTL` | `2592000` (30 d) | Sliding; rotated on every use. |
| `IDEN_AUTH_CODE_TTL` | `60` | Single use. |
| `IDEN_SESSION_TTL` | `86400` (24 h) | Sliding browser session. |
| `IDEN_CHALLENGE_TTL` | `600` | Login/consent challenges. |
| `IDEN_RATE_LIMIT_ENABLED` | `true` | Off only for a load test against a deployment you own. |
| `IDEN_REFRESH_GRACE_PERIOD` | `30` | How long a spent refresh token keeps returning what it was already exchanged for. Set to `0` to make every second use theft — see below. |

### Bootstrap & extensions

| Variable | Default | Purpose |
|---|---|---|
| `IDEN_BOOTSTRAP_ADMIN_EMAIL` | `admin@localhost` | Seeded administrator. |
| `IDEN_BOOTSTRAP_ADMIN_PASSWORD` | *(generated)* | Generated and printed once if unset. |
| `IDEN_BIOMETRIC_ENABLED` | `false` | Mounts `/biometric/*`, seeds the biometric API and scopes, and registers the `face` auth method. |
| `IDEN_ENGINE_BASE_URL` | `http://engine:8000` | Internal biometric engine. Only read when biometric is enabled. |

---

## Package Layout

```text
provider/
├── PLAN.md · README.md · pyproject.toml · alembic.ini · .env.example
├── migrations/                 # Alembic; versions/ holds one file per revision
├── scripts/
│   ├── seed.py                 # idempotent dev bootstrap
│   └── gen_keys.py             # local signing keypair
└── src/provider/
    ├── core/                   # cross-cutting infrastructure
    │   ├── app.py              # FastAPI app, middleware, router mounting
    │   ├── config.py           # Settings
    │   ├── logging.py          # structlog wiring
    │   ├── router.py           # root APIRouter
    │   ├── db.py               # async engine/session, DBSessionDep
    │   ├── redis.py            # redis client, RedisDep
    │   ├── audit.py            # AuditMiddleware, set_actor(), record()
    │   ├── ratelimit.py        # per-address and per-account limits
    │   ├── notifier.py         # outbound messages; logs in dev
    │   ├── security.py         # argon2 hashing, secure random tokens
    │   ├── crypto.py           # signing keys, JWKS, JWT sign/verify
    │   ├── auth.py             # require_scope(), require_fresh_auth()
    │   ├── errors.py           # base domain exception, error contract
    │   └── schemas.py          # CamelCaseBaseModel, paging
    ├── shared/
    │   ├── models.py           # every SQLAlchemy model
    │   ├── enums.py            # ClientType, GrantType, AmrMethod, AcrLevel, …
    │   ├── profile.py          # profile value validation and casting
    │   └── scopes.py           # seeded system API/scope/role catalogue
    ├── authz/
    │   ├── discovery/ oauth/ login/ consent/ logout/ recovery/
    │   └── services/           # scope_resolver · token_service · session_store
    │                           # challenge_store · auth_methods · pkce
    ├── admin/
    │   └── users/ groups/ roles/ apis/ scopes/ clients/ audit/ profile_fields/
    ├── entity/
    │   ├── deps.py             # CurrentUserDep — the subject comes from the token
    │   └── profile/ credentials/ totp/ sessions/ permissions/ connections/
    └── biometric/              # Phase 5 — not built yet
        └── enroll/ verify/ liveness/ search/ · engine_client.py
```

### The feature-package rule

Every resource directory contains exactly four files, each with one job:

| File | Contains | Must not contain |
|---|---|---|
| `routes.py` | FastAPI handlers, OpenAPI metadata, translation of domain exceptions into `HTTPException` | Database calls |
| `schemas.py` | Pydantic request/response DTOs and their validation | Business rules |
| `service.py` | Database and domain logic, raising exceptions from `errors.py` | Any FastAPI import |
| `errors.py` | Domain exceptions | Anything else |

The point of `service.py` being FastAPI-free is that domain logic stays testable and reusable —
`scope_resolver.py` is called from three different modules precisely because it knows nothing about
HTTP.

This is the layout described in [`GUIDELINES.md` section 1](../GUIDELINES.md#1-project-structure) and
`.claude/CLAUDE.md`; the directories above are its concrete form for this service.

---

## Data Model

One source of truth: `shared/models.py`, SQLAlchemy 2.0 async ORM. Sessions, challenges, and the
`jti` denylist deliberately live in Redis with TTLs rather than in Postgres — they are ephemeral by
nature and expiry should be the storage layer's job, not a cleanup cron's.

```mermaid
erDiagram
  USER ||--o{ USER_GROUP : "belongs to"
  GROUP ||--o{ USER_GROUP : "has member"
  USER ||--o{ USER_ROLE : "has"
  ROLE ||--o{ USER_ROLE : ""
  GROUP ||--o{ GROUP_ROLE : "has"
  ROLE ||--o{ GROUP_ROLE : ""
  ROLE ||--o{ ROLE_SCOPE : "bundles"
  SCOPE ||--o{ ROLE_SCOPE : ""
  USER ||--o{ USER_SCOPE : "direct grant"
  SCOPE ||--o{ USER_SCOPE : ""
  RESOURCE_API ||--o{ SCOPE : "defines"
  USER ||--o{ AUDIT_EVENT : "acted (nulled on delete)"
  CLIENT ||--o{ CLIENT_SCOPE : "may request / holds"
  SCOPE ||--o{ CLIENT_SCOPE : ""
  USER ||--o{ USER_PROFILE_VALUE : "has"
  PROFILE_FIELD ||--o{ USER_PROFILE_VALUE : "defines"
  GROUP ||--o{ PROFILE_FIELD : "scopes (optional)"
  USER ||--o| TOTP_CREDENTIAL : "enrolls"
  USER ||--o{ CONSENT_GRANT : "grants"
  CLIENT ||--o{ CONSENT_GRANT : ""
  CLIENT ||--o{ AUTHORIZATION_CODE : "issued"
  USER ||--o{ AUTHORIZATION_CODE : ""
  CLIENT ||--o{ REFRESH_TOKEN : "issued"
  USER ||--o{ REFRESH_TOKEN : ""

  RESOURCE_API {
    uuid id PK
    string name
    string audience UK
    bool is_system
  }
  SCOPE {
    uuid id PK
    uuid api_id FK
    string value
    string description
    bool is_system
  }
  ROLE {
    uuid id PK
    string name UK
    string description
    bool is_system
  }
  GROUP {
    uuid id PK
    string name UK
  }
  USER {
    uuid id PK
    string email UK
    string username UK
    string password_hash
    bool is_active
  }
  PROFILE_FIELD {
    uuid id PK
    string key UK
    string data_type
    bool required
    bool unique
    bool user_readable
    bool user_writable
    uuid group_id FK
    string claim_name
    string claim_scope
  }
  USER_PROFILE_VALUE {
    uuid id PK
    uuid user_id FK
    uuid field_id FK
    string value
  }
  CLIENT {
    uuid id PK
    string client_id UK
    string client_type
    string client_secret_hash
    array redirect_uris
    array allowed_grants
    bool skip_consent
    bool is_system
  }
  REFRESH_TOKEN {
    uuid id PK
    string token_hash
    string scope
    string acr
    array amr
    uuid family_id
    uuid rotated_to_id
    datetime revoked_at
  }
  AUDIT_EVENT {
    uuid id PK
    datetime occurred_at
    string action
    int status_code
    string target
    uuid actor_user_id FK
    string actor_label
    string actor_client
    string ip
    jsonb detail
  }
```

### Invariants worth knowing

| Invariant | Why |
|---|---|
| `is_system` rows cannot be renamed or deleted through the API | An admin deleting `admin:roles:write` would lock the organization out of its own deployment, permanently. |
| At least one active user must hold `admin:users:write` | `is_system` protects the scope catalogue; this protects the *assignment*, which is the other half of the same lockout. Any change leaving nobody able to administer — a deactivation, a deletion, an emptied role or group — is refused with `409`. That scope specifically, because whoever holds it can restore every other one. See `admin/lockout.py`. |
| Authorization codes, refresh tokens, and client secrets are stored **hashed** | A database read must never yield a usable credential. Same reasoning as passwords. |
| `RefreshToken.family_id` + `rotated_to_id` | Rotation with reuse detection: presenting an already-rotated token revokes the whole family, on the assumption it was stolen. |
| `Scope.description` is required | It is the sentence a user reads on the consent screen. An undescribed permission is one nobody can consent to meaningfully. |
| `RefreshToken` carries `acr` and `amr` | A refreshed token must report the same authentication event as the original login, and the login is not repeated on refresh. `acr` is still derived from `amr` — this just remembers which methods were used. |
| `ProfileField.user_writable` defines the self-service surface | `PATCH /entity/profile` has no fixed field list — it accepts exactly the fields an admin marked writable. `student_id` belongs to the registrar; `preferred_name` belongs to the student. Same table, same endpoint, opposite permissions. |
| Profile values live in a table, not a JSONB column | `unique` on `student_id` has to be a database constraint — a check-then-write in the service layer races. Filtering by field stays an indexed query, and renaming a field key rewrites one row instead of every profile. |
| Scope values are globally unique | A token carries scopes as bare strings and the audience is resolved from the value, so two APIs sharing a value would blend their audiences into one token. Namespace by API: `attendance:records:read`. |
| Groups do not nest | Recursive resolution is hard to explain, hard to audit, and hard to make fast. Flat membership covers the real cases. |
| No `tenant_id` on any table | IDEN is single-organization by design — see the [root README](../README.md#single-organization-by-design). |
| A profile value's `is_unique` mirrors its field | An index predicate cannot reach into another table, so the partial unique index needs the flag on the row it indexes. |
| `sid` is a hash of the session id | The id itself is the `iden_session` cookie. Publishing it in every ID token would let any client, or anyone reading a token in transit, set that cookie and become the user. |
| `AuthorizationCode.authenticated_at` is the session's, not the code's | `auth_time` is what a client's `max_age` is measured against. Taking it from the code would make every SSO session look freshly authenticated. |
| `AuditEvent.actor_user_id` is `ON DELETE SET NULL` | Deleting a user must not erase the record of what they did. `actor_label` keeps their email as it was, so the row still names someone after the account is gone. |

---

## Access Control in Practice

### The model in one line

```text
User ──┬── direct scope grants (exceptions)
       ├── direct roles ─────────┐
       └── groups ── group roles ┴──> Role ──> Scopes ──> owned by an API (audience)
```

`effective_user_scopes` is the union of all three sources, computed by
`authz/services/scope_resolver.py` — the single implementation used by token issuance
(`/oauth2/token`), by the admin provenance endpoint (`/admin/users/{id}/effective-scopes`), and by
self-service (`/entity/permissions`).

### What actually lands in a token

| Grant | Formula |
|---|---|
| `authorization_code` | `requested ∩ client.grantable_scopes ∩ effective_user_scopes` |
| `client_credentials` | `requested ∩ client.granted_scopes` |

Pruning is **silent** — asking for more than you hold yields a narrower token, not an error. That is
what allows the dashboard SPA to request a broad scope set at `/authorize` and still behave correctly
for a non-admin user.

Permissions are evaluated **at issuance, never at the resource server**. A resource server verifies
the signature, checks `aud`, and reads `scope`. It never looks up a user, a role, or a group. The
corollary: revoking a role takes effect at the next token issuance, which is why access tokens live
for ten minutes.

### System scope catalogue

Seeded by `scripts/seed.py` from `shared/scopes.py`, all flagged `is_system`.

**API `admin`** — audience `{IDEN_ISSUER}/admin`

| Scope | Allows |
|---|---|
| `admin:users:read` / `admin:users:write` | View / manage users, their roles, and direct grants |
| `admin:groups:read` / `admin:groups:write` | View / manage groups, membership, and group roles |
| `admin:roles:read` / `admin:roles:write` | View / manage roles and their scope bundles |
| `admin:apis:read` / `admin:apis:write` | View / manage registered resource APIs |
| `admin:scopes:read` / `admin:scopes:write` | View / manage scopes under an API |
| `admin:clients:read` / `admin:clients:write` | View / manage OAuth clients and their secrets |
| `admin:audit:read` | Read the audit log. No write scope exists — see below |
| `admin:profile-fields:read` / `admin:profile-fields:write` | View / define the organization's profile fields |

**API `entity`** — audience `{IDEN_ISSUER}/entity`

| Scope | Allows |
|---|---|
| `entity:profile:read` / `entity:profile:write` | Read / update my own profile |
| `entity:credentials:write` | Change my own password |
| `entity:totp:read` / `entity:totp:enroll` | View / enrol and remove my TOTP credential |
| `entity:sessions:read` / `entity:sessions:revoke` | List / revoke my active sessions |
| `entity:connections:read` / `entity:connections:revoke` | See / withdraw the applications I have granted access to |
| `entity:permissions:read` | See my own roles, groups, and effective scopes |

**API `biometric`** — audience `{IDEN_ISSUER}/biometric`, seeded only when `IDEN_BIOMETRIC_ENABLED`

| Scope | Allows |
|---|---|
| `biometric:enroll` | Enrol a face template |
| `biometric:verify` | 1:1 verification against a claimed identity |
| `biometric:search` | 1:N identification (the kiosk's "who is this?") |
| `biometric:liveness` | Liveness check only |

**Seeded roles:** `administrator` (all `admin:*` and `entity:*`) and `member` (all `entity:*`).

### Adding a permission to your own API

The flow the whole design exists to support — no code changes, no redeploy:

1. `POST /admin/apis` — register the API with its audience URI (once).
2. `POST /admin/apis/{id}/scopes` — define `attendance:records:read` with a description.
3. `PUT /admin/roles/{id}/scopes` — bundle it into `attendance-officer`.
4. `PUT /admin/groups/{id}/roles` — give the role to the *Registrar* group.
5. `PUT /admin/clients/{id}/scopes` — allow the calling client to request it.

The next token minted for anyone in that group carries the scope, with `aud` set to the API's
audience. Your resource server validates it against `/.well-known/jwks.json` and needs to know
nothing else about IDEN.

---

## The Audit Log

Every state-changing request writes one row to `audit_events`. There is no way to turn it off and no
endpoint that writes to it — the request being recorded is the only author.

**What counts as state-changing:** any non-`GET` request to `/admin/*`, `/entity/*`,
`/api/v1/auth/*`, or `/oauth2/revoke`, plus `GET /oauth2/logout` — RP-initiated logout is a `GET` by
specification and still destroys a session. Reads are not recorded: an audit log nobody can read
through is one nobody reads, and `GET` volume would bury the writes.

`POST /oauth2/token` is deliberately excluded. A refresh happens every few minutes for every active
session, and the login that authorised it is already in the log.

**What a row holds:**

| Column | Notes |
|---|---|
| `action` | Method plus **route template** — `POST /admin/users/{user_id}/roles`. The template groups; the resolved path would not. |
| `target` | The last path parameter, which is the object being acted on: in `/admin/apis/{api_id}/scopes/{scope_id}` that is the scope. |
| `status_code` | Refused attempts are recorded too. A wall of `403`s from one actor is the signal you want. |
| `actor_user_id` / `actor_label` / `actor_client` | Who, by id, by email-at-the-time, and through which OAuth client. |
| `ip` | The socket peer. `X-Forwarded-For`, if present, goes in `detail` — a header the client sets is a claim, not an observation. |
| `detail` | The request body with secrets redacted, plus the path parameters. |

**Secrets never land in it.** Keys named `password`, `clientSecret`, `token`, `code`, `codeVerifier`
and friends are replaced with `[redacted]` before the row is built, compared with punctuation
stripped so `client_secret` and `clientSecret` are the same key. Only JSON bodies under 4 KB are
captured at all.

**Where it is written.** `core/audit.py`, as pure ASGI middleware rather than a
`@app.middleware("http")` function — reading the request body inside a `BaseHTTPMiddleware` consumes
the stream the endpoint is about to read. The actor comes from `set_actor()`, called by
`require_scope` for token-authenticated routes and by the login and consent steps, which know who the
person is before any token exists.

**One limitation to know about.** The row is written after the response, from a session of its own,
so it is not atomic with the change it describes: if the database becomes unreachable in between, the
change stands and the record is lost. The failure is logged at `error` level rather than swallowed.
Tracked as KI-17 in [PLAN.md](PLAN.md#known-issues).

Read it with `GET /admin/audit`, newest first, filtered by `actorUserId`, `action` (substring),
`since`, and `until`.

---

## Rate Limiting

Argon2 makes a password guess expensive for **the server**, not for the attacker. Unlimited,
`/api/v1/auth/login` is both a credential-stuffing target and a way to exhaust the machine's CPU with
a few hundred requests.

Two different limits, because there are two different attacks:

| Counter | Applies to | Why |
|---|---|---|
| **Per address** — all attempts | login, TOTP, `/oauth2/token`, password reset | Crude flooding from one place. Generous, because an office or a campus is a single address as far as IDEN can tell. |
| **Per account** — failures only | login, TOTP | The one that stops credential stuffing, which rotates addresses and does not rotate the target. |
| **Per email address** — requests | password reset | The endpoint sends mail to someone else. Without it, it is a way to bury a person in messages they never asked for. |

**Failures, not attempts, for the per-account counter.** Counting every attempt against one account
hands anyone a way to lock its owner out: burn the allowance with deliberate nonsense and the real
person is refused. Counting only what went wrong, and clearing it on success, means whoever knows the
password can always still sign in.

**Per-route, not global middleware.** A blanket cap in front of everything is either too loose to
stop credential stuffing or too tight for a dashboard making many legitimate calls. It is also a
dependency rather than middleware, so it runs *after* routing — which means a refusal still lands in
the audit log, and a burst of them is exactly what someone reviewing that log wants to find.

A global cap against crude flooding belongs in the reverse proxy. nginx's `limit_req` can refuse a
connection before Python is involved at all, which is the right place for it.

**Fixed windows, not sliding.** A counter and an expiry, one round trip. The cost is that an attacker
can spend a full allowance at the end of one window and again at the start of the next; for limits of
a handful of attempts per minute, that doubling changes nothing about whether guessing works.

The addresses come from the socket, never from `X-Forwarded-For` — a header the caller sets is a
claim, and trusting it would let anyone spread attempts across as many imaginary addresses as they
like. Behind a proxy every request appears to come from the proxy, which is another reason the proxy
should be doing its own limiting.

---

## Organization-Defined Profiles

IDEN ships no profile fields beyond `email`, `username` and `displayName`. A university needs
`student_id`, `department`, `enrollment_year`; a company needs `employee_id` and `cost_centre`.
Shipping either set would make the other organization's deployment wrong, so administrators define
fields at runtime — the same way they define scopes.

### Why a values table, not a JSONB column

| Reason | Detail |
|---|---|
| Uniqueness is a real constraint | Two students must not end up sharing a number. With JSONB that needs a partial unique index created *per field at runtime* — DDL triggered by an API call — and a check-then-write in the service layer races under load. |
| Filtering has to work | "Everyone in Computer Science" is an indexed query, not a scan over documents. |
| Renaming is free | Values reference `field_id`, so changing a key rewrites one row rather than every profile. |

The cost is that values are stored as text with `dataType` driving the cast at the boundary, plus one
extra query per profile read. Both are acceptable; the constraint story is not negotiable. Keycloak's
`USER_ATTRIBUTE` table has the same shape for the same reasons.

### `userWritable` is what self-service *means*

`PATCH /entity/profile` has no fixed field list. It accepts exactly the fields an administrator
marked writable, and **refuses anything else rather than ignoring it** — a client should never
believe it saved something it did not.

The same values are writable by an administrator through `PATCH /admin/users/{id}/profile`, which is
*not* held to the flag. Being able to write what the field's owner cannot is precisely what
`userWritable: false` means: the registrar sets `student_id`, the student cannot.

`groupId` binds a field to a group, so students and staff get different forms without a second
grouping concept.

### Claims are opt-in

A field is invisible to clients until someone sets both `claimName` and `claimScope`. It then reaches
a token only for a client that was granted that scope — data minimization by default, reusing the
scope system rather than inventing a parallel release mechanism.

`claimName` is checked against the reserved OIDC names (`sub`, `iss`, `aud`, `acr`, `sid`, …), so a
custom field cannot shadow a claim a token's meaning depends on.

---

## Refresh Rotation and the Grace Window

Every refresh is single use: presenting one returns a new one and burns the old. A token presented
twice means two parties hold it, and only one of them can be legitimate, so IDEN revokes the whole
lineage — the family — rather than guessing which.

That is the right instinct and, taken literally, it signs honest people out at random. Two browser
tabs refreshing in the same second, or one request that timed out and was retried, present the same
token twice for entirely innocent reasons and look exactly like theft.

Two mechanisms make the honest cases work without weakening the dishonest one:

- **A replay window.** After a successful exchange, IDEN remembers what that token was exchanged for
  (`IDEN_REFRESH_GRACE_PERIOD`, 30s). Presenting it again inside the window returns the *same* tokens
  rather than rotating again. Only the client the token was issued to can collect the replay, and the
  access token's `expires_in` is recomputed so it still expires when it always would have.
- **A lock on the token.** The window alone only helps a caller that arrives *after* the first
  exchange finished. Two requests firing at the same instant both find no replay yet, both rotate,
  and the loser is treated as theft. The exchange therefore runs under a short Redis lock keyed on
  the token, so the second caller waits and then finds the first one's answer.

**What this costs.** Inside the window a stolen token buys the thief the same tokens the victim just
received, rather than tripping detection. In exchange, both parties then hold the same next token —
so the following exchange collides outside the window and the family is revoked after all. Detection
is delayed by one rotation, not removed. Setting the period to `0` restores strict single use, at the
price of signing people out over a double-click.

---

## Single Sign-On and Sign-Out

The `iden_session` cookie is the single sign-on. A second application redirecting to `/authorize`
finds the session, checks `acr_values` and `max_age` against it, skips consent if it is already on
file, and returns a code — no prompt. Nothing in the applications coordinates that.

### What a client can ask for

| Parameter | Effect |
|---|---|
| `prompt=none` | Never show UI. Returns `login_required`, `consent_required`, or `account_selection_required` to `redirect_uri` instead. This is how a browser app checks silently whether someone is still signed in. |
| `prompt=login` | Re-authenticate even with a live session. The session id survives it — see below. |
| `prompt=consent` | Ask again even where a grant exists. `skipConsent` is the client's default, not a veto over the request. |
| `prompt=select_account` | Treated as `login`. IDEN holds one account per session, so there is nothing to select between; the value is accepted rather than refused so a conforming client is not broken. |
| `max_age` | Seconds. An older login is stepped up, exactly as an unmet `acr_values` is. `max_age=0` means *authenticate now*. |
| `login_hint` | Reaches the Auth UI through the challenge, to prefill the form. A hint, never an assertion — the password still decides. |
| `id_token_hint` | Who the client believes is signed in. A hint naming someone else is treated as no session. Expiry is fine: ID tokens live ten minutes, so a hint about a past login is expected to be stale. |

Two rules are worth knowing because they are easy to get wrong:

- **`prompt=none` creates nothing.** The refusal happens before a challenge is written to Redis. A
  challenge is the pending half of an interaction; one left behind for an interaction that will never
  happen is both a leak and a lie about what took place.
- **Re-authentication keeps the session id.** Minting a new one on `prompt=login` would strand the old
  session in Redis with no cookie pointing at it, and every client holding the old `sid` could never
  be signed out.

### `sid`, and why it is not the cookie

The `sid` claim is `sha256(session id)` — never the session id itself, which is the value of the
`iden_session` cookie and therefore a bearer credential. Publishing that to every client in every ID
token would hand each of them, and anyone who read a token in transit, the ability to set the cookie
and become the user. The hash names the session without being usable as one, and Redis already keys
sessions by that same hash.

### Signing out

`GET /oauth2/logout` does three things, in this order:

1. **Revokes the refresh tokens the session produced** (`refresh_tokens.sid`). Without this a
   signed-out client keeps minting access tokens indefinitely from a token it already holds.
2. **Delivers a logout token** to every client that registered `backchannelLogoutUri` *and* was
   signed into during this session — OIDC Back-Channel Logout 1.0. Which clients those were is
   recorded in Redis as the session goes, because nothing else remembers: a code lives 60 seconds and
   a refresh token may never have been issued.
3. **Clears the session and the cookie**, then redirects to `postLogoutRedirectUri` if it is
   registered for the client named by `clientId` or `idTokenHint`.

A logout token is a signed JWT carrying `sub`, `sid`, and an `events` claim, and **no `nonce`** —
both rules come from the spec, and both exist so it cannot be replayed as proof that someone just
authenticated. IDEN enforces the other direction too: a token carrying `events` is refused as an
`id_token_hint`, so the token that told a client to sign out cannot be turned around as evidence that
someone is signed in.

Delivery is concurrent, best effort, and capped at five seconds. It is **not** retried into a queue —
a relying party that was unreachable re-validates at its next token exchange, and a durable job queue
is a dependency this project does not otherwise need. What is not optional is the record: every
attempt is audited with its outcome, so a sign-out that did not arrive somewhere is visible
afterwards.

Access tokens already issued stay valid until they expire. They are self-contained by design, and
that ten-minute lifetime is the trade that buys offline validation — the `jti` denylist is there for
when it matters sooner.

**A request without a session cookie ends nothing.** `idTokenHint` says who *was* signed in; it is
not a credential for ending someone else's session.

---

## Endpoint Reference

`Auth` column: **public** = no credentials; **client** = client authentication; **bearer** = access
token with the named scope; **session** = browser session cookie. `Phase` refers to [PLAN.md](PLAN.md).

### Service

| Method | Path | Auth | Purpose | Phase |
|---|---|---|---|---|
| `GET` | `/health` | public | Always `200`; the body reports whether PostgreSQL and Redis are reachable, so a monitor can tell *down* from *up and degraded* | 0 |
| `GET` | `/health/live` | public | Liveness. `200` whenever the process can answer at all; touches no dependency. This is what an orchestrator restarts on | 6 |
| `GET` | `/health/ready` | public | Readiness. `503` when PostgreSQL or Redis is unreachable, so a load balancer drains the replica without parsing a body. Never a reason to restart | 6 |

### AuthZ — discovery & OAuth

| Method | Path | Auth | Purpose | Phase |
|---|---|---|---|---|
| `GET` | `/.well-known/openid-configuration` | public | Provider metadata; `scopes_supported` is read live from the database | 1 |
| `GET` | `/.well-known/jwks.json` | public | Public signing keys, one JWK per `kid` | 1 |
| `GET` | `/oauth2/authorize` | session | Start authorization code + PKCE; redirects to `auth-ui` when login or consent is needed. Accepts `prompt`, `max_age`, `login_hint`, `id_token_hint` | 1, 3 |
| `POST` | `/oauth2/token` | client | `authorization_code`, `refresh_token`, `client_credentials` | 1 |
| `GET` | `/oauth2/userinfo` | bearer `openid` | Claims filtered by granted scopes | 1 |
| `POST` | `/oauth2/revoke` | client | RFC 7009 — revoke a refresh family or denylist a `jti`. Public clients may revoke their own tokens | 1 |
| `POST` | `/oauth2/introspect` | client | RFC 7662 — **confidential clients only**: the response describes someone else's token, and a `client_id` is public by definition | 1 |
| `GET` | `/oauth2/logout` | session | Single sign-out: ends the session, revokes its refresh tokens, delivers a logout token to every client it reached | 1, 3 |

### AuthZ — login & consent (consumed by `auth-ui`)

| Method | Path | Auth | Purpose | Phase |
|---|---|---|---|---|
| `GET` | `/api/v1/auth/challenge/{id}` | public | Pending client name + requested scopes, for rendering the page | 1 |
| `POST` | `/api/v1/auth/login` | public | Password login; appends `pwd` to the session `amr` | 1 |
| `POST` | `/api/v1/auth/totp` | session | TOTP verification / step-up; appends `otp` | 1 |
| `POST` | `/api/v1/auth/biometric` | session | Face login; appends `face`. `501` unless biometric is enabled | 1 stub / 4 |
| `POST` | `/api/v1/auth/consent` | session | Persist or deny a consent grant, then resume `/authorize` | 1 |
| `POST` | `/api/v1/auth/password-reset` | public | Begin recovery. Always `202` with an empty body, even for an unknown address — a different answer would enumerate accounts | 4 |
| `POST` | `/api/v1/auth/password-reset/confirm` | public | Single-use token, 15-minute TTL; revokes every session and refresh token on success | 4 |

Login returns `complete` with a `resumeUrl`, or `method_required` with the `methods` still owed —
when the person has an authenticator set up, or the client asked for a level a password alone does
not reach and this person can reach it. It never reports `consentRequired`, and never refuses a level
outright: both are decided by `/authorize`, which is the only endpoint that knows the full picture,
and the browser reaches it again by following `resumeUrl`.

### Admin RS

| Method | Path | Scope | Phase |
|---|---|---|---|
| `GET` `POST` | `/admin/apis` | `admin:apis:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/apis/{id}` | `admin:apis:read` / `:write` | 2 |
| `GET` `POST` | `/admin/apis/{api_id}/scopes` | `admin:scopes:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/scopes/{id}` | `admin:scopes:read` / `:write` | 2 |
| `GET` `POST` | `/admin/roles` | `admin:roles:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/roles/{id}` | `admin:roles:read` / `:write` | 2 |
| `GET` `PUT` | `/admin/roles/{id}/scopes` | `admin:roles:read` / `:write` | 2 |
| `GET` `POST` | `/admin/groups` | `admin:groups:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/groups/{id}` | `admin:groups:read` / `:write` | 2 |
| `PUT` | `/admin/groups/{id}/roles` | `admin:groups:write` | 2 |
| `GET` `POST` | `/admin/groups/{id}/members` | `admin:groups:read` / `:write` | 2 |
| `DELETE` | `/admin/groups/{id}/members/{userId}` | `admin:groups:write` | 2 |
| `GET` `POST` | `/admin/users` | `admin:users:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/users/{id}` | `admin:users:read` / `:write` | 2 |
| `PUT` | `/admin/users/{id}/roles` | `admin:users:write` | 2 |
| `PUT` | `/admin/users/{id}/scopes` | `admin:users:write` | 2 |
| `POST` | `/admin/users/{id}/reset-password` | `admin:users:write` | 2 |
| `GET` | `/admin/users/{id}/effective-scopes` | `admin:users:read` | 2 |
| `GET` `POST` | `/admin/clients` | `admin:clients:read` / `:write` | 2 |
| `GET` `PATCH` `DELETE` | `/admin/clients/{id}` | `admin:clients:read` / `:write` | 2 |
| `POST` | `/admin/clients/{id}/rotate-secret` | `admin:clients:write` | 2 |
| `PUT` | `/admin/clients/{id}/scopes` | `admin:clients:write` | 2 |
| `GET` | `/admin/audit` | `admin:audit:read` | 2 |
| `GET` `PATCH` | `/admin/users/{id}/profile` | `admin:users:read` / `:write` | 4 |
| `GET` `POST` | `/admin/profile-fields` | `admin:profile-fields:read` / `:write` | 4 |
| `GET` `PATCH` `DELETE` | `/admin/profile-fields/{id}` | `admin:profile-fields:read` / `:write` | 4 |

`PUT` on a relationship (`.../roles`, `.../scopes`) **replaces the whole set** rather than adding to
it. Set semantics make the endpoint idempotent and the dashboard's editing UI trivial.

### Entity RS

Every route derives the user from the token's `sub` and never accepts a user id from the caller.

| Method | Path | Scope | Phase |
|---|---|---|---|
| `GET` `PATCH` | `/entity/profile` | `entity:profile:read` / `:write` | 4 |
| `GET` | `/entity/profile/schema` | `entity:profile:read` | 4 |
| `POST` | `/entity/credentials/password` | `entity:credentials:write` + fresh auth | 4 |
| `POST` | `/entity/credentials/email` | `entity:credentials:write` + fresh auth | 4 |
| `POST` | `/entity/totp/enroll` · `/entity/totp/confirm` | `entity:totp:enroll` | 4 |
| `GET` `DELETE` | `/entity/totp` | `entity:totp:read` / `:enroll` | 4 |
| `GET` | `/entity/sessions` | `entity:sessions:read` | 4 |
| `DELETE` | `/entity/sessions/{id}` | `entity:sessions:revoke` + fresh auth | 4 |
| `GET` | `/entity/connections` | `entity:connections:read` | 4 |
| `DELETE` | `/entity/connections/{clientId}` | `entity:connections:revoke` | 4 |
| `GET` | `/entity/permissions` | `entity:permissions:read` | 4 |

Sensitive routes are additionally gated by `require_fresh_auth(max_age=300)`: a valid access token is
not enough to change a password or remove a second factor, because an attacker holding a stolen
token would otherwise take over the account outright. They must pass a login they cannot complete.

### Biometric RS — mounted only when `IDEN_BIOMETRIC_ENABLED=true`

| Method | Path | Scope | Phase |
|---|---|---|---|
| `POST` | `/biometric/enroll` | `biometric:enroll` | 5 |
| `POST` | `/biometric/verify` | `biometric:verify` | 5 |
| `POST` | `/biometric/search` | `biometric:search` | 5 |
| `POST` | `/biometric/liveness` | `biometric:liveness` | 5 |

---

## Tokens & Claims

| Token | Format | Lifetime | Storage |
|---|---|---|---|
| Access | Signed JWT (`RS256`) | 10 min | Stateless; early revocation via a Redis `jti` denylist |
| ID | Signed JWT (`RS256`) | 10 min | Stateless; identity claims only, never sent to an API |
| Refresh | Opaque random string | 30 days, sliding | Hashed in Postgres, rotated on every use, reuse revokes the family. Its stored `scope` is the **original grant**; a `scope` parameter narrows one response without shrinking it |
| Authorization code | Opaque random string | 60 s, single use | Hashed in Postgres, bound to `client_id` + `code_challenge` |

### Access token claims

| Claim | Meaning |
|---|---|
| `iss` | `IDEN_ISSUER` |
| `sub` | User id — or the client id for `client_credentials`, where no person is involved |
| `aud` | Audience of the API owning the granted scopes; a list when scopes span several APIs |
| `client_id` | The client that requested the token |
| `scope` | Space-delimited granted scopes, already pruned |
| `acr` / `amr` | Assurance level and the methods actually used |
| `jti` | Unique id — the handle used for revocation |
| `iat` / `exp` | Issued-at and expiry |

### `amr` and `acr`

`amr` accumulates on the **session** as the user authenticates; `acr` is **derived from `amr` at
issuance time and never stored**. One source of truth means a mid-session step-up automatically
upgrades the next token, with no state to keep in sync.

| `amr` | Method | | `acr` | Requires |
|---|---|---|---|---|
| `pwd` | Password | | `iden:loa:1` | Any single factor |
| `otp` | TOTP | | `iden:loa:2` | Any two factors |
| `face` | Liveness-verified face match | | `iden:loa:3` | `face` plus one more factor |
| `mfa` | Added whenever two or more were used | | | |

A client requests a minimum with `acr_values=iden:loa:2` at `/authorize`; if the session falls short,
IDEN forces a step-up before issuing the code.

Each method is registered in `authz/services/auth_methods.py`. That registry is the seam that lets
the biometric module add `face` without the AuthZ core knowing anything about faces.

### Validating an IDEN token from your own resource server

1. Fetch and cache `{issuer}/.well-known/jwks.json`; select the key by the token header's `kid`.
2. Verify the signature, then `iss`, `exp`, and — critically — that `aud` contains **your** API's
   audience. Skipping the `aud` check means accepting a token minted for a different service.
3. Check that the required scope is present in `scope`.
4. Do not look up the user. Everything you are authorized to know is in the token.

---

## Request Lifecycle

Where a request goes, and which file owns each step:

```text
nginx
  → core/app.py            request-id + structlog binding
  → rate limiter           Redis fixed window                       (Phase 6)
  → CORS / security headers
  → routes.py              validate the request body via schemas.py
      · resource server?   core/auth.require_scope(...)
                           verify signature + iss + aud + exp
                           reject denylisted jti  → 401
                           check required scope   → 403
      · authz endpoint?    session_store / challenge_store
  → service.py             DB work via DBSessionDep; raises domain errors
  → routes.py              domain error → HTTPException
  → core/errors.py         → the documented JSON error shape
```

`401` versus `403` is a deliberate distinction: `401` means *authenticate again*, `403` means
*authentication will not help — you lack the scope*.

---

## Conventions

Beyond `CODING_STYLE.md`, which applies in full:

### Every endpoint documents itself

`/docs` is the contract the frontends are built against, so an endpoint that is not self-explanatory
there is not finished:

```python
@router.post(
    "",
    response_model=ScopeResponse,
    status_code=201,
    summary="Create a scope",
    description=(
        "Defines a new permission under the given API.\n\n"
        "**Required scope:** `admin:scopes:write`"
    ),
    responses={
        404: {"description": "API not found"},
        409: {"description": "A scope with this value already exists for the API"},
    },
    dependencies=[Depends(require_scope("admin:scopes:write"))],
)
```

Rules: explicit `response_model` (never inferred from the return type), explicit `status_code` for
non-200 successes (`201` create, `204` delete), `summary` and `description` always, `responses` for
every documented non-2xx, `tags` on the router, `Field(description=...)` on non-obvious fields, and
`Literal[...]` for enums so allowed values show up in the docs.

### Tests belong to the phase that adds the code

Pure logic gets unit tests with no database and no fixtures — the scope resolver, PKCE, and acr
derivation are the highest value per line in the suite. Every endpoint gets at least a success case,
an authorization failure, and its most interesting failure mode. A test name should state the rule
being enforced (`test_reuse_revokes_the_whole_family`), not the mechanics.

### Query parameters are camelCase too

FastAPI does not apply Pydantic's alias generator to query parameters, so multi-word ones need an
explicit alias: `Query(None, alias="groupId")`. Without it a caller sending `groupId` gets an
unfiltered list rather than an error — a filter that quietly returns everything is worse than one
that fails.

### Loading relationships on new objects

A freshly constructed model has its relationships *unset*, not empty. Reading one after `commit()`
triggers a lazy load, which fails inside async code with an unhelpful greenlet error. Either assign
the related object you already have, or `await session.refresh(obj)` before returning it. This is
the single most common way to break an async SQLAlchemy route here.

### Layers

`routes.py` never touches the database. `service.py` never imports FastAPI. Domain exceptions are
raised in services and translated in routes — that is the only place `HTTPException` appears.

### Secrets

All password and client-secret hashing goes through `core/security.py` (argon2id). Cleartext secrets
are returned **once**, on create and on rotate, and are never stored or logged.

### Logging

Use the configured structlog logger, never `print()`. Every log line already carries a `request_id`
from the middleware. Log identifiers, not payloads — never a password, token, secret, or face image.

### Errors

One JSON error shape everywhere, except the OAuth endpoints, which must keep the RFC 6749 format
(`error`, `error_description`) or clients will not understand them.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `invalid_client` on `/oauth2/token` | `client_id` unknown, wrong secret, or the client is not allowed that grant. Check `allowed_grants`. |
| `invalid_grant` with a fresh code | The code expired (60 s), was already used, `redirect_uri` differs from the authorize request, or the PKCE verifier does not match. |
| Token validates but the resource server rejects it | Almost always `aud`. The scopes granted belong to a different API than the one being called. |
| Signature verification fails after a restart | `gen_keys` regenerated the keypair. Tokens signed with the old key are unverifiable; re-authenticate. |
| `403` on an `/admin/*` route with a valid token | The user's roles do not include that scope, or the client's grantable set does not, so it was pruned at issuance. Check `/admin/users/{id}/effective-scopes`. |
| `401` where you expected `403` | The token is for a different API. Audience is validated before scopes, so a token carrying only `entity:*` gets `401` at an `/admin/*` route — not `403`. `403` means right audience, missing scope. |
| Scope changes have no effect | Access tokens live 10 minutes. Refresh, or wait for expiry. |
| `409` deleting a scope or role | Either it is `is_system` (seeded entries are immutable by design), or it is still granted to someone — pass `force=true` once revoking those permissions is the intent. |
| A filter seems to be ignored | Query parameters are camelCase (`?groupId=`, `?isActive=`). An unrecognised one is dropped, and you get an unfiltered list. |
| `MissingGreenlet` in a route | A relationship was read on a newly created object. Assign it explicitly or `await session.refresh(obj)` after commit. |
| `/biometric/*` returns 404 | `IDEN_BIOMETRIC_ENABLED` is false, so the module is not mounted. |
