# Run it locally

The provider on your own machine, in about five minutes. This is the page for reading the code,
running the tests, or pointing an integration at something you control.

For the whole system — the provider plus both frontends, in containers — see
[Install it for your organization](install.md).

## You need

- **Python 3.14+** and [uv](https://docs.astral.sh/uv/)
- **Docker**, for PostgreSQL and Redis

## Start the backing services

Only the three stores run in Docker here. The provider itself runs on your machine, so you can
restart it, attach a debugger, and read its logs directly.

```bash
# From the repository root
docker compose -f deploy/docker-compose.yml up -d postgres redis seaweedfs
```

| Service | Holds |
|---|---|
| **PostgreSQL 18** with pgvector, on 5432 | People, permissions, clients, tokens |
| **Redis 8**, on 6379 | Sessions, pending sign-ins, the denylist, rate limits |
| **SeaweedFS**, on 8333 | Profile photos, over the S3 API. Optional — leave `IDEN_S3_ENDPOINT_URL` empty to skip it |

Naming the three services matters: `up -d` on its own would also start the provider and both
frontends in containers, and their published ports would collide with the ones you are about to use.

## Start the provider

```bash
cd provider

uv sync                              # install dependencies
cp .env.example .env                 # then read it — every setting is commented

uv run python -m scripts.gen_keys    # signing key + totp.key; the provider will not start without them
uv run alembic upgrade head          # create the schema
uv run python -m scripts.seed        # permissions, bootstrap admin, two clients

uv run provider                      # http://localhost:8000
```

Two of those deserve a note.

**`gen_keys`** writes one date-stamped PEM into `provider/keys/`, plus `totp.key` beside it. IDEN
refuses to start without a signing key and will not invent one silently, because a key nobody can
account for is not a key you want signing tokens. `totp.key` encrypts TOTP secrets at rest — the one
credential IDEN cannot hash, since verifying a code means recomputing it. Back both up together.

**`seed`** prints two credentials, **once**:

```text
Seeded 28 system scopes across 3 APIs.

  Bootstrap administrator — shown once, change it after first login
    email:    admin@localhost
    password: _qajl3wRjjx6QsuXMO9YY5tw

  Kiosk client secret — shown once, it is hashed in the database
    client_id:     kiosk
    client_secret: 7ZJbgK2um1y9QeliyysqElTJ-SUhC_8R8aXRygrmUgM
```

They are hashed on the way into the database and cannot be recovered. Losing them means seeding a
fresh database — or, since this is development, running
[`scripts.reset`](../contributing/development.md).

## Check it worked

| What | URL |
|---|---|
| Interactive API docs | <http://localhost:8000/docs> |
| OIDC discovery | <http://localhost:8000/.well-known/openid-configuration> |
| Health | <http://localhost:8000/health> |

Discovery is the interesting one — it is the document every OIDC client library reads to configure
itself, and it is generated from the live deployment rather than written by hand. `scopes_supported`
is read from the database, so permissions you define appear there without a restart.

## What the seed created

| | Detail |
|---|---|
| **Two APIs** | `admin` and `entity` — IDEN's own, with all 25 of their [permissions](../reference/scopes.md) |
| **Two roles** | `administrator` (everything) and `member` (self-service only) |
| **One person** | The bootstrap administrator |
| **`dashboard`** | A public client for the browser: PKCE, consent skipped, callbacks on ports 3000 and 5173 |
| **`kiosk`** | A confidential client for machine-to-machine access |

The seed is idempotent — re-run it any time. It creates nothing structural; that is
[Alembic's job](../contributing/migrations.md).

## Sign in end to end

The fastest way to watch a real flow is the test suite, which drives one in-process:

```bash
uv run pytest tests/test_auth_code_flow.py -v
```

To drive it by hand, see [Add a web application](web-application.md). To get the sign-in page and the
dashboard in a browser, see [Run the frontends](run-the-frontends.md).

## Starting over

```bash
uv run python -m scripts.reset
```

Drops the schema, flushes Redis, re-migrates, and re-seeds — so you get a fresh bootstrap password.
It refuses to run when `IDEN_ENV=prod`.

## Common problems

??? failure "`connection refused` on port 5432"
    PostgreSQL has not finished starting. `docker compose -f deploy/docker-compose.yml ps` should
    show it healthy.

??? failure "`No schema found. Run alembic upgrade head first.`"
    Exactly what it says — the seed refuses to half-fill an unmigrated database.

??? failure "`No signing keys in keys`"
    `scripts.gen_keys` has not run, or `IDEN_SIGNING_KEY_DIR` does not point where it wrote.

??? failure "Ports 8000, 4000 or 3000 are already in use"
    A previous `docker compose up -d` started the containerized provider or frontends. Stop them with
    `docker compose -f deploy/docker-compose.yml stop provider auth-ui dashboard`.

??? failure "The sign-in round trip loses the session"
    Cookies are host-scoped. Whatever drives the flow must reach IDEN on the same host as
    `IDEN_ISSUER`, or the session cookie is never sent back — `localhost` and `127.0.0.1` are two
    different hosts to a browser.
