# IDEN Frontends

The two browser applications that make IDEN usable by people rather than by `curl`.

| App           | Port            | Path        | What it is                                                                                           |
| ------------- | --------------- | ----------- | ---------------------------------------------------------------------------------------------------- |
| **auth-ui**   | 4000            | `/auth/`    | The hosted login. `/oauth2/authorize` redirects here; it is the only place a password is ever typed. |
| **dashboard** | 3000 (dev 5173) | `/console/` | One SPA for both administrators and ordinary people. Navigation renders from the token's scopes.     |

Both are served from a sub-path, in `pnpm dev` as well as in a container, because a deployment puts
all three applications on one origin. The dashboard cannot be at the root there: the provider's API
owns `/admin/*` and the dashboard's own admin screens have the same names.

Each app's path is Vite's `base`. Everything else derives from it — the built asset URLs, React
Router's `basename`, the OIDC redirect URI — so it is changed in one place and rebuilt.

Both are React 19 + TypeScript on Vite, sharing `@iden/shared` — design tokens, the generated API
types, one axios client, and the components that render identity data.

The build plan is [PLAN.md](PLAN.md); the visual system is [../DESIGN.md](../DESIGN.md).

---

## Running it

The provider has to be up first — these apps have nothing to show without it. From `provider/`:

```bash
docker compose -f ../deploy/docker-compose.yml up -d postgres redis
uv run alembic upgrade head
uv run python -m scripts.seed          # prints the bootstrap admin password, once
uv run python -m uvicorn provider.core.app:app --port 8000
```

Then from `web/`:

```bash
pnpm install
pnpm dev            # auth-ui on :4000/auth/, dashboard on :5173/console/
```

Open <http://localhost:5173/console/>. It redirects to `/oauth2/authorize`, which redirects to
auth-ui, which brings you back signed in. The dev server redirects its own root to the base, so
<http://localhost:5173> gets you there too.

Or run everything in containers, which serves the dashboard on its production port:

```bash
docker compose -f ../deploy/docker-compose.yml up --build
```

---

## Layout

```text
web/
├── shared/                    # @iden/shared
│   ├── tokens/theme.css       # DESIGN.md, transcribed once
│   ├── api/
│   │   ├── schema.d.ts        # generated — do not edit
│   │   ├── client.ts          # the one axios instance
│   │   ├── errors.ts          # IdenError: { code, message, details }
│   │   └── page.ts            # usePage<T> over the Page envelope
│   ├── scopes.ts              # mirrors provider/shared/scopes.py
│   └── ui/                    # shadcn primitives + ScopeChip, ProvenanceTrace, DataTable…
├── auth-ui/src/routes/        # login, consent, forgot, reset
└── dashboard/src/
    ├── app/                   # shell, router, OIDC, the axios binding
    └── features/              # one folder per resource, mirroring provider/admin/*
```

## Types

TypeScript types come from the provider's own OpenAPI document, never hand-written:

```bash
pnpm gen:api        # reads the FastAPI app directly — no running server needed
```

Regenerate after any change to a provider schema, and commit the result.

## Checks

```bash
pnpm lint
pnpm typecheck
pnpm build
```

## Configuration

| Variable                                     | Where      | Meaning                                                                                                                                                     |
| -------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VITE_IDEN_ISSUER`                           | `pnpm dev` | The provider's origin. Defaults to `http://localhost:8000`.                                                                                                 |
| `IDEN_ISSUER`                                | container  | Written into `/config.js` at start-up, so one image serves any deployment.                                                                                  |
| `VITE_IDEN_ORG_NAME` / `IDEN_ORG_NAME`       | both       | The organization this deployment belongs to. It takes the larger type in the brand lockup and IDEN drops to a caption beneath it. Unset, IDEN stands alone. |
| `VITE_IDEN_ORG_LOGO` / `IDEN_ORG_LOGO_URL`   | both       | Optional logo shown beside the organization name. Any URL the browser can reach.                                                                            |
| `VITE_IDEN_MAIL_DOMAIN` / `IDEN_MAIL_DOMAIN` | both       | Dashboard only. Shown beside the email field when adding a user. The provider decides the address; give both the same value.                                   |

Whichever origin serves the dashboard must appear in the provider's
`IDEN_ALLOWED_ADMIN_ORIGINS`, and be registered as a redirect URI on the `dashboard` client —
credentialed CORS forbids a wildcard, and redirect URIs are matched exactly.

`IDEN_AUTH_UI_BASE_URL` pins auth-ui's origin, and the provider redirects to the fixed paths
`/auth/login`, `/auth/consent` and `/auth/reset`. Those three are part of the contract.
