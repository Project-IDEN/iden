# Run the frontends

The development loop for the two browser applications themselves. To *deploy* them, see
[Install it for your organization](install.md) — this page is about editing them and seeing the
change.

IDEN ships two. They are what turns the API into something a person can use, and both are ordinary
OIDC clients of the provider with no privileged path of their own.

| App | Dev port | Container port | Path | What it does |
|---|---|---|---|---|
| **auth-ui** | 4000 | 4000 | `/auth/` | The hosted sign-in page. `/oauth2/authorize` redirects here for the password step, TOTP, consent, and password recovery. The only place a password is typed. |
| **dashboard** | 5173 | 3000 | `/console/` | Administration and self-service in one app. What you see is decided by the scopes in your token. |

Both are served from a **sub-path**, in development as well as in a container, because in a real
deployment all three applications share one origin. The dashboard cannot sit at the root there: the
provider's API owns `/admin/*` and the dashboard's own admin screens have the same names.

The path is Vite's `base` in each app's `vite.config.ts`, and everything else follows from it — the
built asset URLs, React Router's `basename`, the OIDC redirect URI. Change it in one place and
rebuild; change it anywhere else and the two disagree.

Both are React on Vite in the `web/` pnpm workspace, sharing an `@iden/shared` package: the design
tokens, the generated API types, one axios client, and the components that render identity data.
[`web/README.md`](https://github.com/yephonekyaw/iden/blob/dev/web/README.md) has the layout.

The dev ports differ from the container ports for the dashboard, and both are already accounted for:
5173 and 3000 are in the CORS allowlist and in the seeded `dashboard` client's redirect URIs, so
either works without configuration.

## 1. Start the provider

The frontends have nothing to show without it. From `provider/`:

```bash
docker compose -f ../deploy/docker-compose.yml up -d postgres redis seaweedfs

uv run python -m scripts.gen_keys    # once — the provider will not start without its keys
uv run alembic upgrade head
uv run python -m scripts.seed        # prints the bootstrap password, once
uv run provider                      # http://localhost:8000
```

Leave `seaweedfs` out if you are not working on profile photos; those endpoints will answer `503` and
nothing else changes. [Run it locally](quickstart.md) explains these steps in more detail.

## 2. Start the frontends

From `web/`:

```bash
pnpm install
pnpm dev
```

`pnpm dev` runs both apps in parallel. auth-ui serves on 4000 and the dashboard on 5173, both with
`strictPort` — if a port is taken, Vite fails rather than quietly moving, because a moved port breaks
the redirect URI.

Open <http://localhost:5173/console/> and you are sent through a real sign-in: the dashboard
redirects to `/oauth2/authorize`, the provider redirects to auth-ui at
<http://localhost:4000/auth/login>, and you come back to `/console/callback` with a code.

Note the trailing paths — though you do not have to type them. All three ways of serving these apps
redirect their root to the base: Vite's dev server, each app's own container, and the production
proxy. <http://localhost:5173> and <http://localhost:3000> both land on `/console/`, so the dev loop
and the deployment agree about where things live.

### Pointing them somewhere else

Both read their configuration at runtime, not at build time, so one image serves any deployment. In
`pnpm dev` that comes from Vite env vars; in a container it comes from `/config.js`, written by the
entrypoint.

| Variable | Effect |
|---|---|
| `VITE_IDEN_ISSUER` | The provider's origin — what these apps call. In `pnpm dev` it is a different origin from the app itself, so the app's own origin (5173 or 4000) must be in `IDEN_ALLOWED_ADMIN_ORIGINS`: CORS permits the caller, not the callee. Behind one origin in production, nothing needs listing. |
| `VITE_IDEN_ORG_NAME` | Whose sign-in page this is. Takes the larger type; IDEN drops to a caption beneath it. |
| `VITE_IDEN_ORG_LOGO` | Optional, sits beside the name. |

Each app has an `.env.example` next to its `package.json` — copy it to `.env` and edit. The container
equivalents drop the `VITE_` prefix: `IDEN_ISSUER`, `IDEN_ORG_NAME`, `IDEN_ORG_LOGO_URL`.

## Types come from the server

Request and response types are generated from the provider's own OpenAPI document, never written by
hand:

```bash
pnpm gen:api
```

It reads the schema out of the FastAPI application directly rather than over HTTP, so it works with
no server, database, or Redis running. Re-run it after changing any provider schema, and commit the
result — `web/shared/api/schema.d.ts` is checked in.

If a type is wrong, the fix is in `provider/`. Editing the generated file is undone by the next
person who runs the generator.

## Before you commit

```bash
pnpm lint
pnpm typecheck
pnpm build
```

The same three run in CI (`.github/workflows/web.yml`). Conventions are in
[GUIDELINES.md — Frontend Code][guidelines]; the visual system is `DESIGN.md`, transcribed once into
`web/shared/tokens/theme.css` — every colour and size resolves there rather than being written
inline.

## When something is wrong

??? failure "The dashboard redirects forever and never signs in"
    The issuer, the CORS allowlist, and the registered redirect URI do not all name the same origin.
    All three are compared exactly, and the browser console says which one — a CORS refusal points at
    `IDEN_ALLOWED_ADMIN_ORIGINS`, an `invalid_request` on the redirect points at the client.

    The settings, and how to change them, are in
    [Install it for your organization](install.md#3-configure).

??? failure "Vite refuses to start: port is already in use"
    `strictPort` is deliberate. Something else holds 4000 or 5173 — usually the containerized
    frontends from an earlier `docker compose up -d`. Stop them with
    `docker compose -f ../deploy/docker-compose.yml stop auth-ui dashboard`.

??? failure "Every API call fails with a CORS error"
    The origin you are serving from is not in `IDEN_ALLOWED_ADMIN_ORIGINS`. Credentialed requests
    forbid a wildcard, so it has to be named, and the provider has to be restarted after a change.

??? failure "Sign-in works but the dashboard shows no Administration section"
    That is the permission system working. The sidebar is built from the scopes in your token — sign
    in as someone holding the `administrator` role.

[guidelines]: https://github.com/yephonekyaw/iden/blob/dev/GUIDELINES.md
