# IDEN Frontends — Build Plan

The phased plan for building the two browser applications in `web/`. Read
[../README.md](../README.md) for the system-level architecture and
[../provider/README.md](../provider/README.md) for the API these apps consume; read this file for the
**order of work**.

Each phase states its goal, the files it creates, the screens it delivers, and a **Done when** check
you can run by hand. Build phases in order: each one is runnable and verifiable before the next
begins.

> Scope note: this plan covers the two browser frontends only. The server they consume is planned in
> [../provider/PLAN.md](../provider/PLAN.md), and the kiosk devices separately. This is **Phase 7**
> of the roadmap in the root [README](../README.md#development-phases).

---

## Table of Contents

- [Ground rules](#ground-rules)
- [Target workspace layout](#target-workspace-layout)
- [Design system](#design-system)
- [Phase 7.0 — Workspace foundation](#phase-70--workspace-foundation)
- [Phase 7.1 — Shared API layer](#phase-71--shared-api-layer)
- [Phase 7.2 — auth-ui](#phase-72--auth-ui)
- [Phase 7.3 — Dashboard shell and self-service](#phase-73--dashboard-shell-and-self-service)
- [Phase 7.4 — Dashboard admin](#phase-74--dashboard-admin)
- [Phase 7.5 — Integration and hardening](#phase-75--integration-and-hardening)
- [Why this order](#why-this-order)

---

## Ground rules

These apply to every phase. They are the frontend reading of what `GUIDELINES.md` already says,
collected here so a phase can be executed without flipping between files.

1. **Feature folders, not layers.** A resource lives in one directory:
   `routes.tsx` (screens), `api.ts` (queries and mutations), `schemas.ts` (zod), `components/`
   (pieces used only by this feature). Anything a second feature needs moves to `shared/`.
2. **The server is the source of truth for types.** Request and response types are generated from
   `/openapi.json`, never hand-written. If a type is wrong, the fix is in `provider/`.
3. **No `any`, no non-null `!`.** The generated types already describe every field; if something is
   genuinely unknown it is `unknown` and narrowed at the boundary.
4. **Server state is TanStack Query's.** Zustand holds the auth session and nothing else. A
   `useState` that mirrors a query result is a bug.
5. **Simplest thing that reads well.** Three similar screens beat one configurable screen. No
   abstraction over a resource until a second resource actually needs it.
6. **Comment only the why.** A spec requirement, a browser quirk, a server behaviour that surprises.
   Never narrate what the code does.
7. **Every colour and size comes from a token.** No inline hex, no magic pixel values. The design
   system lives once, in `shared/tokens/`.
8. **Every screen has four states.** Loading, empty, error, and populated — the empty and error
   states written deliberately, not defaulted. An empty screen says what to do next; an error says
   what happened and how to fix it.
9. **The quality floor is not optional.** Responsive to 360px, a visible focus ring on everything
   interactive, `prefers-reduced-motion` respected, dialogs focus-trapped. It ships with the phase,
   not after it.

### Checks

Run all three from `web/` before committing:

```bash
pnpm lint          # eslint, typescript-eslint
pnpm typecheck     # tsc --noEmit across the workspace
pnpm build         # vite build, both apps
```

---

## Target workspace layout

```text
web/
├── package.json               # workspace scripts only
├── pnpm-workspace.yaml
├── tsconfig.base.json
├── eslint.config.js
├── shared/                    # @iden/shared — consumed by both apps
│   ├── tokens/                # DESIGN.md as Tailwind v4 @theme + fonts
│   ├── api/
│   │   ├── schema.d.ts        # generated from /openapi.json — do not edit
│   │   ├── client.ts          # the one axios instance
│   │   ├── errors.ts          # IdenError, the { code, message, details } contract
│   │   └── page.ts            # usePage<T> over the Page envelope
│   ├── scopes.ts              # the scope catalogue, mirroring shared/scopes.py
│   └── ui/                    # re-skinned shadcn primitives + IDEN components
├── auth-ui/                   # :4000 — the hosted login
│   └── src/routes/            # login, consent, reset, forgot
└── dashboard/                 # :3000 (dev :5173) — the SPA
    └── src/
        ├── app/               # shell, router, auth provider
        └── features/          # one folder per resource
```

### Why one workspace and not two repositories

Both apps render the same scope chips, parse the same error contract, and are built from the same
design tokens. Two copies of that drift within a phase. The apps themselves share no routes and no
state — only the layer underneath them.

---

## Design system

The visual system is [DESIGN.md](../DESIGN.md), followed as written: cream canvas `#faf9f5`, coral
`#cc785c` used scarcely, dark `#181715` surfaces, a serif display at weight 400 with negative
tracking, humanist sans body, monospace for code. Fonts are self-hosted through `@fontsource` —
EB Garamond, Inter, JetBrains Mono, the substitutes DESIGN.md's own _Known Gaps_ section names for
the licensed Copernicus and StyreneB. A CDN link is not an option: the provider's CSP is
`default-src 'none'`, and IDEN is meant to deploy without internet egress.

DESIGN.md documents a marketing surface. It has no table, no sidebar, and no form-heavy screen, so
the product layer is **derived from its tokens** rather than invented beside them:

| Added token           | Value                                            | Derived from                                                                   |
| --------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------ |
| `--surface-row-hover` | `#f5f0e8`                                        | the existing `surface-soft`                                                    |
| `--focus-ring`        | coral at 15% alpha, 3px, plus a 1px coral border | already specified for `text-input-focused`; promoted to everything interactive |
| `--density-row`       | 44px                                             | the WCAG touch target, matching the 40px control height                        |

The trinity rule holds: cream, coral, dark. No fourth surface tone.

### The signature — the provenance trace

The most characteristic thing in IDEN's world is not a statistic. It is the answer to _why can this
person do that?_ — and the server already returns it. `GET /admin/users/{id}/effective-scopes` and
`GET /entity/permissions` annotate every scope with `viaDirect`, `viaRoles[]` and `viaGroups[]`,
where a group entry reads `"Students → member"`.

So a scope renders as a monospace chip with its derivation trailing it:

```text
admin:users:write      ← administrator
entity:profile:read    ← Students → member
attendance:records:read ← granted directly
```

One component, four screens, real information each time: the admin user detail, the user's own
permissions page, the **consent screen** (where the derivation is replaced by the admin-written scope
description the challenge endpoint returns), and the client detail. Monospace is the identity
vernacular throughout — scope values, `client_id`, audience URIs, UUIDs, `jti`. That is the one bold
thing; everything around it stays quiet.

**No `01 / 02 / 03` numbering anywhere.** None of these screens is a sequence. The one place ordering
carries information — the audit log — uses timestamps, which is what the reader actually needs.

**Motion is one orchestrated moment**: the auth-ui card resolving between steps (password → TOTP →
consent) as a height-animated crossfade, so a step-up reads as the same conversation continuing
rather than a new page. Everything else is a 120ms state transition and nothing more.
`prefers-reduced-motion` cuts all of it.

---

## Phase 7.0 — Workspace foundation

**Status: done.** pnpm workspace, the token layer, both Vite apps, ESLint/Prettier and the CI job all landed; `pnpm lint && pnpm typecheck && pnpm build` is clean.

**Goal:** a pnpm workspace where both apps build, lint, and typecheck clean, and serve an empty shell
already wearing the design system. Nothing talks to the server yet.

### 7.0.1 The workspace — `web/package.json`, `web/pnpm-workspace.yaml`

Three packages: `@iden/shared`, `@iden/auth-ui`, `@iden/dashboard`. Apps depend on shared through the
`workspace:*` protocol. Root scripts (`dev`, `build`, `lint`, `typecheck`, `gen:api`) fan out with
`pnpm -r`.

`web/` was in `.gitignore` — the rule is narrowed to `web/**/node_modules/` and `web/**/dist/` so the
source is tracked.

### 7.0.2 Design tokens — `web/shared/tokens/`

DESIGN.md transcribed **once** as a Tailwind v4 `@theme` block: every colour, the type scale with its
letter-spacing, the radius scale, the spacing scale. Plus the `@fontsource` imports. Both apps import
this one stylesheet; neither declares a colour of its own.

### 7.0.3 App skeletons — `web/auth-ui/`, `web/dashboard/`

Vite + React 19 + TypeScript, react-router in library mode (`createBrowserRouter`). auth-ui serves on
4000 because `IDEN_AUTH_UI_BASE_URL` pins that origin and the provider redirects to the fixed paths
`/auth/login`, `/auth/consent`, `/auth/reset`. The dashboard serves on 5173 in development — already
in the provider's CORS allowlist and its seeded redirect URIs — and 3000 in a container.

### 7.0.4 Lint, format, CI — `web/eslint.config.js`, `.github/workflows/web.yml`

typescript-eslint with `no-explicit-any` and `no-non-null-assertion` as errors, Prettier for format.
A CI job mirroring the Python one: `pnpm lint`, `pnpm typecheck`, `pnpm build`.

`GUIDELINES.md` gains a frontend section — the feature-folder rule, no `any`, no barrel re-exports,
why-only comments — so its Section 1 "organize by feature, not by layer" has a stated frontend reading.

### Done when

```bash
cd web && pnpm install
pnpm lint && pnpm typecheck && pnpm build     # all clean
pnpm dev                                       # :4000 and :5173 both serve a themed shell
```

---

## Phase 7.1 — Shared API layer

**Status: done.** Types generate from the FastAPI app directly rather than over HTTP, so a clone can regenerate them without a running server — `pnpm gen:api` reads `app.openapi()` through `uv`.

**Goal:** one typed way to call the provider, one typed way to read its errors, and the components
that render identity data. After this phase a screen is a query plus a layout.

### 7.1.1 Generated types — `web/shared/api/schema.d.ts`

`pnpm gen:api` runs `openapi-typescript` against a running provider's `/openapi.json`. The output is
committed so a clone builds without a server; CI re-runs it against a live provider and fails on
drift. Nothing in this file is edited by hand.

Note the wire format: response bodies are **camelCase** (`CamelCaseBaseModel`), except `/oauth2/*`
and `/.well-known/*`, which are snake_case per spec.

### 7.1.2 The client — `web/shared/api/client.ts`, `errors.ts`

One axios instance, `baseURL` from `VITE_IDEN_ISSUER`. A response interceptor narrows every failure
into a typed `IdenError { code, message, details }` — the contract `core/errors.py` guarantees. The
422 shape `details.fields[]` carries `{ field: "body.email", message }`, which react-hook-form
consumes directly by stripping the `body.` prefix and calling `setError`.

Three responses every screen must survive, handled once here:

| Response                                                                                       | Handling                                                                                                                        |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **401**                                                                                        | The token is gone or revoked. Re-authenticate; do not retry.                                                                    |
| **403** with `WWW-Authenticate: Bearer error="insufficient_user_authentication" … max_age=300` | RFC 9470 step-up. Restart `/authorize` with `max_age=300` and return the user to the same form.                                 |
| **429**                                                                                        | Surface the `Retry-After` seconds as a countdown. Never retry automatically — the limit is per-address and retrying deepens it. |
| **503** with `Retry-After: 5`                                                                  | Postgres or Redis is unreachable. Say so; this is not the user's fault.                                                         |

### 7.1.3 Pagination — `web/shared/api/page.ts`

`usePage<T>()`, a thin TanStack Query wrapper over `{ items, meta: { total, limit, offset } }` with
`limit` (default 50, max 200) and `offset`. Every paginated list endpoint uses it; the four Entity
endpoints that return a plain envelope (`sessions`, `connections`, `permissions`, `profile/schema`)
deliberately do not.

### 7.1.4 Scopes — `web/shared/scopes.ts`

The 15 `admin:*` and 10 `entity:*` scopes as typed constants, mirroring `provider/shared/scopes.py`.
`useHasScope()` and `<RequireScope>` read the access token's `scope` claim. Because pruning at
issuance is silent, the token is the only honest source of what this person may do — never the user
record, never a role name.

### 7.1.5 Components — `web/shared/ui/`

shadcn primitives re-skinned from the tokens, plus what the tokens do not cover:

| Component                       | Purpose                                                                                                                                    |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `ScopeChip` / `ProvenanceTrace` | The signature. A scope and where it came from.                                                                                             |
| `DataTable`                     | List rows at `--density-row`, sortable where the server sorts, stacked cards below 640px.                                                  |
| `EmptyState`                    | An invitation to act, never "No data".                                                                                                     |
| `ConfirmDialog`                 | Names what will happen, including what else is affected on a `force=true` delete.                                                          |
| `SecretRevealOnce`              | Client secrets and generated passwords: shown once, copyable, with the fact that it will not be shown again stated before it is dismissed. |

### Done when

A throwaway screen lists `/admin/users` against a running provider with a real token, renders the
loading, empty and error states, and a forced 429 shows a countdown rather than a spinner.

---

## Phase 7.2 — auth-ui

**Status: done.** The whole round-trip was driven by hand: `/authorize` → challenge → login → resume → code → token, with the right `aud`, `acr` and `amr` on the result.

**Goal:** every credential path the provider supports, driven from the browser: password, TOTP
step-up, consent, and password recovery. This is the phase that makes the dashboard reachable.

auth-ui uses **no OIDC library**. It is not an OAuth client — it is the provider's own front end,
speaking the challenge API with `credentials: "include"` because the responses set `iden_session`.

### 7.2.1 The challenge — `web/auth-ui/src/routes/login.tsx`

`/authorize` redirects here as `/auth/login?challenge=<id>` (plus `step_up=1` when re-authentication
is being forced). `GET /api/v1/auth/challenge/{id}` returns the requesting client's name, the
requested scopes with their descriptions, `acrValues`, `authenticated`, and `loginHint`.

The hero of this page is therefore **the application asking**, not a greeting. The user is told which
app wants in and what it is asking for, before the password field.

`POST /api/v1/auth/login { challengeId, email, password }`:

| `status`        | Next                                                                                           |
| --------------- | ---------------------------------------------------------------------------------------------- |
| `complete`      | Navigate to `resumeUrl` — back into `/authorize`, which issues the code or bounces to consent. |
| `totp_required` | The card morphs into the code step. Same challenge, same conversation.                         |

`step_up=1` changes the copy: the app is asking them to confirm it is still them, not telling them
they are signed out.

The method picker renders the biometric option only when discovery advertises it, so the Phase 5
`501` stub is never reachable from the UI.

### 7.2.2 Consent — `routes/consent.tsx`

The same challenge read, scopes rendered as `ScopeChip`s carrying the admin-written description.
`POST /api/v1/auth/consent { challengeId, approved }` returns `redirectUrl`, which is navigated to on
**both** approve and deny — denial is a protocol outcome (`access_denied`), not an error.

### 7.2.3 Recovery — `routes/forgot.tsx`, `routes/reset.tsx`

`POST /api/v1/auth/password-reset` always answers 202, so the copy confirms a mail was sent _if the
address is registered_ and never confirms an account exists. The link lands on
`/auth/reset?token=…`; `POST /api/v1/auth/password-reset/confirm` answers 204, and the 422
`invalid_reset_token` gets a real way forward rather than a dead end.

### 7.2.4 Failure states

Written deliberately, because this app is where a stuck user has nowhere else to go:

| Case                               | What the screen says                                                                                          |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| 404 — challenge expired or unknown | The sign-in link expired; return to the application and start again.                                          |
| 401 on password                    | Email and password don't match. A disabled account answers the same, so it cannot confirm a guessed password. |
| 429                                | How many seconds until they can try again, counting down.                                                     |
| 401 on TOTP                        | The session is gone; start the sign-in again.                                                                 |

### Done when

The whole login round-trip works by hand: `/oauth2/authorize` → login → TOTP → consent → back to the
client with a code, and a password reset completes end to end.

---

## Phase 7.3 — Dashboard shell and self-service

**Status: done.** Sign-out uses a credentialed fetch rather than a navigation, because the seeded client has no `post_logout_redirect_uri` and the provider answers 204 — a navigation there leaves the browser where it was.

**Goal:** a signed-in dashboard whose navigation is built from the token, and every Entity RS screen
a person needs to manage their own account.

### 7.3.1 OIDC — `web/dashboard/src/app/auth.tsx`

`react-oidc-context` over `oidc-client-ts`, the pair `doc/guides/oidc-libraries.md` already
recommends to IDEN's users — the dashboard should be the reference integration. `client_id:
dashboard`, public, PKCE S256, `/callback`, silent renew via `prompt=none`.

The requested scope is `openid profile email` plus every `admin:*` and `entity:*` scope. Asking
broadly is correct, not greedy: `granted = requested ∩ client.grantable ∩ effective_user_scopes`, and
pruning is silent, so a member simply receives a narrower token.

The callback route is guarded against React StrictMode's double-effect. Authorization codes are
single-use, and `doc/guides/troubleshooting.md` names a double-submitting React effect as the
first thing to check when a code is rejected.

Sign-out navigates to `/oauth2/logout?id_token_hint=…`. The seeded dashboard client has an empty
`post_logout_redirect_uris`, so the provider answers **204, not a redirect** — the app treats that as
success and routes itself home. Registering a post-logout URI is an admin's choice, not a
precondition.

### 7.3.2 The shell — `src/app/shell.tsx`

Cream canvas, dark sidebar, content column capped at the DESIGN.md 1200px. Navigation renders from
token scopes: a person holding only `entity:*` sees Account and nothing else — not a greyed-out admin
section advertising what they cannot have.

### 7.3.3 Account — `src/features/account/`

| Screen      | Endpoints                                                                                                                                                                                                                   |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Profile     | `GET /entity/profile`, `PATCH`, and `GET /entity/profile/schema` — **the form is rendered from the schema**, never hardcoded. The zod schema is built at runtime from each field's `dataType`, `required` and `validators`. |
| Credentials | `POST /entity/credentials/password`, `/email` — both behind the 300s fresh-auth step-up, which the shared interceptor already knows how to satisfy.                                                                         |
| Two-factor  | `GET /entity/totp`, `POST /enroll` → QR rendered from the returned `uri` → `POST /confirm`; removal needs fresh auth.                                                                                                       |
| Sessions    | `GET /entity/sessions` with the current one marked, `DELETE /{id}` behind fresh auth. Each row shows `amr` and which applications used it.                                                                                  |
| Connections | `GET /entity/connections`, `DELETE /{clientId}` — withdrawing consent. First-party `skipConsent` clients never appear here, which is correct and worth a line of copy.                                                      |
| Permissions | `GET /entity/permissions` as `ProvenanceTrace` — the signature, on the screen where a person asks what they are allowed to do.                                                                                              |

### Done when

Sign in as the bootstrap administrator, enrol TOTP, sign out, sign in again through the TOTP step,
change the password through a step-up, and revoke another session.

---

## Phase 7.4 — Dashboard admin

**Status: done.** All seven resources, each gated on its read scope.

**Goal:** the full Admin RS surface, one feature folder per resource, mirroring the server's own
`provider/admin/<resource>/` split.

Each resource is the same shape — list with filters, detail, mutate — so the phase is seven passes of
a known pattern rather than seven designs.

### 7.4.1 Users — `src/features/users/`

The richest surface. Search plus `groupId` / `roleId` / `isActive` filters; create with the
`generatedPassword` shown once; role and direct-scope assignment as full-replace pickers (the server
replaces, so the UI must show the resulting set, not a diff); admin password reset, whose
`sessionsRevoked: true` is stated in the confirmation rather than discovered later; the profile tab
against `/admin/users/{id}/profile`; and the effective-scopes trace.

### 7.4.2 Groups, roles — `src/features/{groups,roles}/`

Groups hold roles (full replace) and members (add many, remove one). Roles bundle scopes across APIs.

Roles is where the **last-administrator guard** lives: a 409 from `admin/lockout.py` renders as an
explanation of why the deployment refuses to lock itself out, not a generic conflict toast. `isSystem`
roles present as immutable up front, never editable-then-rejected.

### 7.4.3 APIs and scopes — `src/features/apis/`

Scopes are nested under their API, because that ownership is the entire point of the model — a scope
belongs to the backend that defines it, not to the app that requests it. `force=true` deletes go
through `ConfirmDialog` naming what else is affected (`api_in_use`, `scope_in_use`).

### 7.4.4 Clients — `src/features/clients/`

Create and rotate reveal the secret once through `SecretRevealOnce`. Public clients show no secret
affordance at all rather than a disabled one. Grantable and granted scopes are presented as the two
distinct questions they are: what a user _may_ delegate to this app, versus what the app holds on its
own through `client_credentials`.

### 7.4.5 Profile fields — `src/features/profile-fields/`

The definition UI for the schema 7.3's profile form renders from. `dataType`, `unique`, `key` and
`groupId` are immutable after creation and presented that way.

### 7.4.6 Audit — `src/features/audit/`

Reverse-chronological, filters on `actorUserId` / `action` / `since` / `until`, each row expanding to
its `detail` object. Read-only by design — there is no write scope, and the screen should not imply
one.

### Error handling across all seven

Every domain code maps to a field-level message, not a toast: `email_taken` and `username_taken` to
their inputs, `unknown_scopes` / `unknown_roles` / `unknown_users` to the picker that produced them,
`*_name_taken` to the name field. A toast is for what succeeded.

### Done when

An administrator can, entirely through the UI: register an API, define a scope on it, bundle it into
a role, assign the role to a group, add a user to that group, and then read that scope back on the
user's effective-scopes page traced through both hops.

---

## Phase 7.5 — Integration and hardening

**Status: done**, except the visual pass — the screens have been verified functionally and in containers, not reviewed in a browser.

**Goal:** the difference between "it runs on my machine with three terminals open" and "it deploys".

### 7.5.1 Server configuration

`http://localhost:3000` joins `IDEN_ALLOWED_ADMIN_ORIGINS` in `provider/.env.example`. Today it lists
only `:5173`, while the seed registers a `:3000/callback` redirect URI — so the containerised
dashboard would pass the redirect check and then fail CORS.

### 7.5.2 Containers — `web/*/Dockerfile`, `deploy/docker-compose.yml`

Two-stage builds: `node:22-alpine` to build, `nginx:alpine` to serve static assets with an SPA
fallback. Added to the existing compose file following its anchor and healthcheck patterns.

Configuration is injected at container start as `/config.js`, not baked in at build time, so one
image serves any issuer. A Vite `import.meta.env` build would need a rebuild per deployment.

### 7.5.3 The reverse proxy — `deploy/nginx/iden.conf.example`

The routing the README has always diagrammed but the repository has never contained. Shipped as a
reference configuration rather than a compose service: `deploy/docker-compose.yml` says in its own
header that the proxy is the operator's, and adding one would contradict that. The routing is:

| Path                                                                            | Upstream  |
| ------------------------------------------------------------------------------- | --------- |
| `/oauth2/*`, `/.well-known/*`, `/api/v1/*`, `/admin/*`, `/entity/*`, `/health*` | provider  |
| `/auth/*`                                                                       | auth-ui   |
| `/*`                                                                            | dashboard |

Only nginx publishes ports. TLS stays the operator's, as `deploy/docker-compose.yml` already says.

### 7.5.4 The quality floor

Responsive to 360px — tables become stacked cards rather than horizontal scroll, except the audit
detail, which keeps its own `overflow-x`. A visible coral focus ring on everything interactive.
`prefers-reduced-motion` honoured. Dialogs focus-trapped. Mutation results announced to a live region,
because a toast that only exists visually is invisible to a screen reader.

### 7.5.5 Documentation

`web/README.md` (what the workspace is, how to run both apps, the environment variables), a
`doc/guides/` page on running the frontends, and the `mkdocs.yml` nav entry.

### Done when

`docker compose up` from a clean clone gives a working sign-in at `http://localhost`, and the root
README's Phase 7 row can be marked Done.

---

## Why this order

1. **Tokens and the client before any screen**, because both apps need them and retrofitting a design
   system across finished screens means touching every file twice.
2. **auth-ui before the dashboard**, because the dashboard cannot be signed into until it exists. The
   ordering is forced by the protocol, not chosen.
3. **Self-service before admin**, because it is the smaller surface against the simpler resource
   server, and it proves the token, the shell, the step-up interceptor and the schema-driven form
   before those are load-bearing under seven admin resources.
4. **Admin as one phase**, because its seven resources are the same pattern seven times. Splitting
   them would create phases that differ only in noun.
5. **Hardening last**, for the same reason the backend left it last: a Dockerfile written against a
   build that is still moving costs more than it saves.

Phase 8 (kiosk) consumes this work and is planned separately.
