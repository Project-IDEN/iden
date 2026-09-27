# On a laptop, in Docker

The whole system, meaning the provider, the sign-in page and the dashboard, running in containers on
`localhost`. Use it to try IDEN, demo it, or check a change end to end.

Budget **about fifteen minutes**, most of it the first build. The only thing you install on the host
is Docker.

This setup is for your own machine only. Every port is published on `127.0.0.1`, the stores use
passwords that are printed in the repository, and nothing uses TLS. To put IDEN on the internet,
follow [Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md) instead.

## You need

- **Docker with Compose.** `docker compose version` should answer.
- Ports **8000, 4000, 3000, 5432, 6379 and 8333** free on `127.0.0.1`.

## 1. Get the code

```bash
git clone https://github.com/Project-IDEN/iden.git
cd iden
```

Every command below runs from this directory.

!!! warning "Don't copy `deploy/.env.example` on this path"
    Any setting missing from `deploy/.env` falls back to a laptop default, and that's what this page
    relies on. `deploy/.env.example` is written for a public deployment and sets `IDEN_ENV=prod`
    with an `https://` issuer. If you copy it here, the provider refuses to start.

## 2. Generate the keys

IDEN signs every token with an RSA private key that you own. It **refuses to start without one** and
never creates one on its own. The same command also writes `totp.key`, which encrypts
authenticator secrets at rest.

Build the provider image, then run the generator inside it, so you don't need Python on the host:

```bash
docker compose -f deploy/docker-compose.yml build provider

mkdir -p provider/keys
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/provider/keys:/keys" -e IDEN_SIGNING_KEY_DIR=/keys \
  --entrypoint python iden-dev-provider:latest -m scripts.gen_keys
```

```text
Wrote signing key: /keys/iden-20260927.pem (kid: iden-20260927)
Wrote secret-encryption key: /keys/totp.key
```

**Check it worked:** `ls provider/keys/` shows one `.pem` file and `totp.key`.

!!! info "Why `mkdir` and `--user`"
    The image runs as uid **1000**, which is almost certainly not your uid. Without these two flags,
    on Linux you get `Permission denied`, because Docker creates a missing bind-mount directory as
    `root`. Creating the directory yourself and running the container as your own uid avoids that,
    and the keys stay owned by you. Docker Desktop on macOS hides the problem, so the shorter command
    works on a Mac and then fails on a Linux server.

## 3. Start everything

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

Startup runs in a fixed order. PostgreSQL, Redis and SeaweedFS start and report healthy, then
`migrate` creates the schema and exits, and only then does the provider start.

**Check it worked:**

```bash
docker compose -f deploy/docker-compose.yml ps -a
```

Six services running, and `migrate` exited with code `0`. If `migrate` failed, nothing else will
work. Run `docker compose -f deploy/docker-compose.yml logs migrate` to see why.

```bash
curl -s http://localhost:8000/health
```

```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

If the status is `degraded`, the response names the dependency that isn't answering.

## 4. Create the first administrator

The schema is there but empty. The seed fills it with IDEN's own permission catalogue, the starting
roles, one administrator, and two clients.

```bash
docker compose -f deploy/docker-compose.yml exec provider python -m scripts.seed
```

```text
Seeded 27 system scopes across 3 APIs.

  Bootstrap administrator — shown once, change it after first login
    email:    admin@localhost
    password: _qajl3wRjjx6QsuXMO9YY5tw

  Kiosk client secret — shown once, it is hashed in the database
    client_id:     kiosk
    client_secret: 7ZJbgK2um1y9QeliyysqElTJ-SUhC_8R8aXRygrmUgM
```

!!! warning "Write both down before you close the terminal"
    Both are hashed before they're stored and can't be recovered. On a laptop, if you lose one, the
    fix is [starting over](#starting-over).

| Created | Detail |
|---|---|
| **Three APIs** | `admin`, `entity` and `developer`, with their 27 [permissions](../reference/scopes.md) |
| **Three roles** | `administrator` (everything), `member` (self-service only), and `developer` (self-service plus registering their own applications) |
| **One person** | The bootstrap administrator, holding the `administrator` role |
| **`dashboard`** | A public client for the browser, using PKCE and skipping consent as a first-party app. Its callbacks are `localhost` on ports 8000, 3000 and 5173, so it works as-is. |
| **`kiosk`** | A confidential client for machine-to-machine access |

The seed is **idempotent**, so you can re-run it any time. On a database that's already seeded, it
prints `Nothing new to create` and leaves existing credentials alone.

## 5. Sign in

Open <http://localhost:3000/console/>. The dashboard redirects you to the sign-in page at
<http://localhost:4000/auth/login>, and back again once you sign in. That round trip means the whole
system is working. The dashboard is an ordinary OIDC client of the provider, with no special access
of its own.

**Change the bootstrap password now**, under **Security**.

| URL | What it is |
|---|---|
| <http://localhost:3000/console/> | The dashboard |
| <http://localhost:4000/auth/login> | The sign-in page |
| <http://localhost:8000/docs> | The provider's interactive API docs |
| <http://localhost:8000/.well-known/openid-configuration> | OIDC discovery |

Next, work through **[After installing](first-steps.md)**, which checks every part of the system and
covers setting up your organization.

## Branding it

Both frontends and the provider read the organization's name and mail domain from `deploy/.env`.
On a laptop, create that file with only the lines you want to change. Everything you leave out
keeps its laptop default:

```bash
cat > deploy/.env <<'EOF'
IDEN_ORG_NAME=Example University
IDEN_MAIL_DOMAIN=example.org
EOF

docker compose -f deploy/docker-compose.yml up -d
```

Use `up -d`, not `restart`. A container's environment is fixed when it's created, and `restart`
reuses the same container.

Set `IDEN_MAIL_DOMAIN` **before you add anyone**. Every account an administrator creates is
`<name>@<this domain>`, and the address can't be changed afterwards. See
[Configuration](../reference/configuration.md) for every setting.

## Day to day

| To | Run |
|---|---|
| Stop it, keeping the data | `docker compose -f deploy/docker-compose.yml down` |
| Start it again | `docker compose -f deploy/docker-compose.yml up -d` |
| Follow the provider's log | `docker compose -f deploy/docker-compose.yml logs -f provider` |
| Pick up new code | `git pull && docker compose -f deploy/docker-compose.yml up -d --build`, then re-run the seed if the release added permissions |

### Starting over

```bash
docker compose -f deploy/docker-compose.yml down -v
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml exec provider python -m scripts.seed
```

`-v` deletes the PostgreSQL, Redis and SeaweedFS volumes. You get a fresh database and a new
bootstrap password. The keys in `provider/keys/` stay.

## Common problems

??? failure "`Permission denied` writing the keys"
    The image runs as uid 1000 and can't write to `provider/keys`. Use the `mkdir` and `--user` form
    from [step 2](#2-generate-the-keys). If the directory already belongs to `root`, which happens
    when Docker created it for you, remove it with `sudo rm -r provider/keys` and run step 2 again.

    If you have Python and `uv` on the host, running `cd provider && uv run python -m scripts.gen_keys`
    works too.

??? failure "`Read-only file system: '/keys/iden-....pem'`"
    The generator ran inside the *running* provider (`docker compose exec provider ...`), and the
    Compose file mounts the keys read-only on purpose. Use the standalone `docker run` from
    [step 2](#2-generate-the-keys).

??? failure "`No signing keys in /keys`"
    Step 2 was skipped, or `provider/keys` didn't exist when Docker mounted it, so Docker created an
    empty one. Generate the keys, then run `docker compose -f deploy/docker-compose.yml restart provider`.

??? failure "`Refusing to start with an unsafe configuration`"
    `deploy/.env` sets `IDEN_ENV=prod` or an `https://` issuer, usually because it was copied from
    `deploy/.env.example`. On a laptop, remove those lines and run `up -d` again.

??? failure "`No schema found. Run alembic upgrade head first.`"
    `migrate` hasn't finished, or it failed. `docker compose -f deploy/docker-compose.yml logs migrate`
    shows which.

??? failure "`port is already allocated`"
    Something else is using one of the ports, often a provider started with `uv run provider` or
    frontends started with `pnpm dev`. Stop those and run `up -d` again.

??? failure "Signing in works, then the dashboard signs out immediately"
    Usually the clock. Access tokens last ten minutes, so a container whose clock has drifted issues
    tokens that have already expired. Compare `date` inside the provider container with the host.

??? failure "Profile photo upload answers `503`"
    SeaweedFS isn't reachable. `docker compose -f deploy/docker-compose.yml ps` should show it
    healthy. Every other feature works without it.

More in [Troubleshooting](troubleshooting.md).
