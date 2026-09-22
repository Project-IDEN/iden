# Install IDEN for your organization

This page takes you from an empty directory to a working deployment with a signed-in administrator,
and then checks every part of it before anyone else is let in.

Budget **about thirty minutes**: ten to get it running, twenty to walk through the verification at
the end. Everything runs in Docker, so the only thing you install on the host is Docker itself.

!!! tip "Just want to look at the server?"
    [Run it locally](quickstart.md) starts the provider alone in about five minutes, without the
    frontends. Come back here when you want the whole system.

## What you are installing

Six containers. `docker compose` builds and wires all of them.

| Service | Port | What it is |
|---|---|---|
| **provider** | 8000 | The application itself. OIDC, administration, and self-service in one process. |
| **auth-ui** | 4000 | The hosted sign-in page, served under `/auth`. The only place a password is ever typed. |
| **dashboard** | 3000 | Administration and self-service, served under `/console`. What each person sees is decided by their permissions. |
| **PostgreSQL 18** | 5432 | People, permissions, clients, tokens. The data that matters. |
| **Redis 8** | 6379 | Sessions, pending sign-ins, the token denylist, rate-limit counters. |
| **SeaweedFS** | 8333 | S3-compatible object storage for profile photos. Optional — see below. |

A seventh service, `migrate`, runs the database migrations to completion and then exits. It is a
separate service rather than a startup step inside the provider so that running two provider replicas
does not run the migrations twice, concurrently, against the same database.

!!! info "The object store is optional"
    Leave `IDEN_S3_ENDPOINT_URL` empty and IDEN runs without it — profile photo endpoints answer
    `503` and every other feature works normally. The compose file includes SeaweedFS because it is
    Apache-2.0 and runs as a single process, but the provider speaks the S3 API and nothing else, so
    MinIO, Garage, or AWS S3 work by changing the endpoint and credentials.

One deployment serves **one organization**. There is no tenant concept anywhere, and your own staff
are the administrators rather than a vendor's — see [Single-organization by design](../index.md).

## Before you start

**Docker with Compose.** That is the only requirement. `docker compose version` should answer.

**Decide your hostname now.** If this is going anywhere but your laptop, settle on the URL people
will use before step 3, not after. The issuer is baked into every token and compared character for
character, so changing it later invalidates every token and session in circulation.

Throughout this page, `https://iden.example.org` stands for that hostname. On a laptop the defaults
already work and you can leave every value alone.

---

## 1. Get the code

```bash
git clone https://github.com/yephonekyaw/iden.git
cd iden
```

Every command below runs from this directory unless it says otherwise.

## 2. Generate a signing key

IDEN signs every token it issues with an RSA private key that you own. It **refuses to start without
one**, and it will not generate one silently — a key that appears by magic is a key whose provenance
nobody can account for.

Build the provider image first, then run the key generator inside it. This way you do not need Python
on the host:

```bash
docker compose -f deploy/docker-compose.yml build provider

mkdir -p provider/keys
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/provider/keys:/keys" -e IDEN_SIGNING_KEY_DIR=/keys \
  --entrypoint python iden-dev-provider:latest -m scripts.gen_keys
```

!!! info "Why `mkdir` and `--user`"
    The image runs as an unprivileged user with uid **1000**, which is almost certainly not yours.
    Without these two, on Linux you get `Permission denied`: Docker creates a missing bind-mount
    directory as `root`, and the container is not root.

    Creating the directory yourself and telling the container to write as you avoids it, and leaves
    the key owned by you rather than by a uid you would need `sudo` to touch again.

    Docker Desktop on macOS maps ownership and hides this, so the plainer command works on a laptop
    and then fails on a Linux server.

```text
Wrote signing key: /keys/iden-20260907.pem (kid: iden-20260907)
```

**Check it worked:** `ls provider/keys/` shows one `.pem` file.

The filename stem becomes the key's `kid`, and keys sort by name — which is what makes
[rotation](../reference/configuration.md#rotating-a-signing-key) a matter of adding a file rather
than running a migration.

!!! danger "Back this directory up, separately from the database"
    Anyone who can read these keys can mint a token for anyone. Losing them signs everyone out
    permanently. Keep them out of the image, mount them read-only, and back them up somewhere you
    would be comfortable keeping a password.

    `gen_keys` is for getting started. In production, mount the key from wherever your organization
    already keeps secrets, and never commit it.

## 3. Configure

Everything the deployment needs is in `deploy/docker-compose.yml`.

=== "On a laptop"

    Nothing to do. The defaults point at `localhost` and every port is published. Skip to step 4.

=== "On a real hostname"

    Copy the environment file and edit that — not `docker-compose.yml`, which is tracked and would
    conflict on your next upgrade:

    ```bash
    cp deploy/.env.example deploy/.env
    ```

    ```bash
    IDEN_ENV=prod                              # Secure cookie, HSTS, no /docs
    IDEN_ISSUER=https://iden.example.org
    IDEN_AUTH_UI_BASE_URL=https://iden.example.org
    IDEN_ALLOWED_ADMIN_ORIGINS=[]
    ```

    All three applications sit on that one origin, so the issuer and the Auth UI base URL are the
    same value, and the frontends pick it up from the same file.

    `IDEN_ALLOWED_ADMIN_ORIGINS` stays **empty**: it permits *cross*-origin credentialed requests,
    and on one origin the dashboard's calls are not cross-origin. Name an origin there only for a
    browser application on some other host that calls the provider directly.

    A fourth value — the `dashboard` client's registered redirect URIs — is set in the database
    rather than in a file. Step 6 covers it.

### Why these are compared exactly

Getting one of them wrong produces a sign-in loop rather than an error message, which is why they are
worth reading carefully.

| Setting | What compares it |
|---|---|
| `IDEN_ISSUER` | Every client library validates the `iss` claim against it, character for character. It is the identity of this deployment. |
| `IDEN_AUTH_UI_BASE_URL` | The origin `/oauth2/authorize` sends people to. The paths `/auth/login`, `/auth/consent` and `/auth/reset` are fixed and appended to it, so this is an origin and never includes `/auth` itself. |
| `IDEN_ALLOWED_ADMIN_ORIGINS` | Credentialed CORS forbids a wildcard, so every browser origin that calls the provider directly must be named. |
| The `dashboard` client's redirect URIs | Matched exactly — no wildcards, no prefix matching, no trailing-slash forgiveness. |

### Naming your organization

Both frontends show whose sign-in page this is. Set it on `auth-ui` and `dashboard`:

```yaml
environment:
  IDEN_ORG_NAME: "Example University"
  IDEN_ORG_LOGO_URL: "https://example.org/logo.svg"   # optional
```

The organization takes the larger type and IDEN drops to a caption beneath it. Leave `IDEN_ORG_NAME`
empty and IDEN stands alone. Both are read at container start rather than baked in at build time, so
one image serves any deployment.

Give `IDEN_ORG_NAME` to the `provider` service as well — `deploy/docker-compose.yml` already does.
It is the name an authenticator app files a TOTP credential under, so someone who enrolls sees
`Example University: you@example.org` beside their code rather than the issuer URL.

### Putting it behind one hostname

All three belong on one origin, so the session cookie is unambiguously first-party:

| Path | Serves |
|---|---|
| `/.well-known/*`, `/oauth2/*`, `/api/v1/auth/*`, `/admin/*`, `/entity/*`, `/media/*` | provider |
| `/auth/*` | auth-ui |
| `/console/*` | dashboard |
| `/` | redirects to `/console/` |

Two of those are fixed rather than chosen. Discovery must be at the **host root**, which is why
`IDEN_API_PREFIX` must stay empty. And the dashboard cannot be at the root: the provider's API owns
`/admin/*` and the dashboard's own admin screens have the same names, so on one origin
`/admin/users` has to be either the API or the page.

`deploy/nginx/iden.conf.example` is a tested configuration for exactly this.
[Deployment](../operations/deployment.md#behind-a-proxy) explains what any proxy has to do —
particularly `IDEN_FORWARDED_ALLOW_IPS`, without which every caller looks like the proxy.

To put that origin on the internet with no inbound port at all, follow [Behind a Cloudflare
Tunnel](../operations/cloudflare-tunnel.md).

## 4. Start everything

=== "On a laptop"

    ```bash
    docker compose -f deploy/docker-compose.yml up -d --build
    ```

    Every port is published on `127.0.0.1`, so the provider is at
    <http://localhost:8000> and the two frontends at
    <http://localhost:4000/auth/login> and <http://localhost:3000/console/>.

=== "On a real hostname"

    Add the tunnel overlay, which puts nginx in front of all three applications and opens no
    inbound port at all:

    ```bash
    cp deploy/nginx/iden.conf.example deploy/nginx/iden.conf

    docker compose -f deploy/docker-compose.yml \
                   -f deploy/docker-compose.tunnel.yml up -d --build
    ```

    This needs `CLOUDFLARE_TUNNEL_TOKEN` in `deploy/.env` and a tunnel whose public hostname points
    at `nginx:80`. Both are in [Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md) —
    read that page before this step rather than after, because several Cloudflare settings have to
    change too.

    Terminating TLS on your own proxy instead is fine; use `deploy/nginx/iden.conf.example` as the
    routing and add a `listen 443 ssl` block with your certificates.

The first build takes a few minutes. Startup then runs in a fixed order: PostgreSQL, Redis and
SeaweedFS come up and report healthy, `migrate` creates the schema and exits, and only then does the
provider start.

**Check it worked:**

```bash
docker compose -f deploy/docker-compose.yml ps
```

Six services running, and `migrate` shown as `exited (0)`. If `migrate` exited non-zero, nothing else
will work — read `docker compose -f deploy/docker-compose.yml logs migrate` before going on.

Then ask the provider itself:

```bash
curl -s http://localhost:8000/health
```

```json
{"status": "ok", "database": "ok", "redis": "ok"}
```

`degraded` here names the dependency that is not answering.

## 5. Create the first administrator

The schema exists but is empty. The seed fills it: IDEN's own permission catalogue, the two starting
roles, one administrator, and two clients.

```bash
docker compose -f deploy/docker-compose.yml exec provider python -m scripts.seed
```

```text
Seeded 28 system scopes across 3 APIs.

  Bootstrap administrator — shown once, change it after first login
    email:    admin@localhost
    password: _qajl3wRjjx6QsuXMO9YY5tw

  Kiosk client secret — shown once, it is hashed in the database
    client_id:     kiosk
    client_secret: 7ZJbgK2um1y9QeliyysqElTJ-SUhC_8R8aXRygrmUgM
```

!!! warning "Write both down before you close the terminal"
    They are hashed on the way into the database and cannot be recovered. If you lose the
    administrator password, the only way back in is a fresh database.

    Set `IDEN_BOOTSTRAP_ADMIN_EMAIL` in `deploy/.env` *before* the first seed to choose the
    address. To choose the password too, give it to that one command rather than to the
    deployment — a password in `deploy/.env` would live in the container's environment for as long
    as the container does:

    ```bash
    docker compose -f deploy/docker-compose.yml exec \
      -e IDEN_BOOTSTRAP_ADMIN_PASSWORD='...' provider python -m scripts.seed
    ```

    Both apply **only when the seed creates the account**. Against an administrator that already
    exists the seed changes nothing — it never resets a credential — so setting a new email later
    creates a *second* administrator rather than renaming the first.

### What it created

| | Detail |
|---|---|
| **Two APIs** | `admin` and `entity`, with all 25 of their [permissions](../reference/scopes.md) |
| **Two roles** | `administrator` (everything) and `member` (self-service only) |
| **One person** | The bootstrap administrator, holding the `administrator` role |
| **`dashboard`** | A public client for the browser: PKCE, and consent skipped as a first-party app |
| **`kiosk`** | A confidential client for machine-to-machine access |

The seed is **idempotent** — re-run it any time, including after an upgrade that ships new
permissions. Running it again on a seeded database prints `Nothing new to create` and leaves existing
credentials untouched. It creates nothing structural; that is
[Alembic's job](../contributing/migrations.md).

## 6. Point the dashboard client at your hostname

Skip this on a laptop — the seeded client already allows `http://localhost:3000/console/callback`
and `http://localhost:5173/console/callback`.

Anywhere else, the `dashboard` client's redirect URIs still name localhost, and the sign-in will loop
until they name your origin.

This is a bootstrap problem: the **Clients** screen and the admin API both edit this, and both need
you to be signed in — which is the thing that is broken. So do it in the database:

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -U iden -d iden -c \
  "update clients set redirect_uris = ARRAY['https://iden.example.org/console/callback']
   where client_id = 'dashboard';"
```

`redirect_uris` is a PostgreSQL array (`character varying[]`), not JSON, so it is `ARRAY[...]` and
not a bracketed string — a JSON literal fails with *malformed array literal*. Note
`/console/callback`: the dashboard's redirect URI moved with the app.

**Check it worked.** A wrong value here presents as a sign-in loop rather than an error, so it is
worth ten seconds now:

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  psql -U iden -d iden -c \
  "select client_id, redirect_uris from clients where client_id = 'dashboard';"
```

```text
 client_id |                redirect_uris
-----------+---------------------------------------------
 dashboard | {https://iden.example.org/console/callback}
```

Once you can sign in, the dashboard's **Clients** page is the place to change this. The admin API
can too, though it identifies a client by its UUID rather than by `dashboard`, so it takes a lookup
first:

```bash
curl -X PATCH https://iden.example.org/admin/clients/{uuid} \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"redirectUris": ["https://iden.example.org/console/callback"]}'
```

## 7. Sign in

Open <http://localhost:3000/console/> — or your own hostname. Either way `/` redirects there, so
the bare address works too.

You are redirected to the sign-in page, and back to the dashboard afterwards. That round trip is the
whole system working: the dashboard is an ordinary OIDC client of the provider, with no special path
of its own.

**Change the bootstrap password immediately**, under **Security**. A password that was printed to a
terminal and pasted into a chat window is not a password.

---

## Check every part works

Fifteen minutes, entirely through the two applications. Each row exercises a different part of the
system, and the order matters — later rows depend on earlier ones.

### Signing in

| Do this | You should see |
|---|---|
| Open the dashboard signed out | The sign-in page, naming the application that is asking |
| Sign in with the bootstrap password | The dashboard, with an **Administration** section in the sidebar |
| **Security** → set up an authenticator, scan the QR code, confirm | Two-factor on |
| Sign out, then sign in again | The code step now appears after the password |
| **Sessions** | This browser listed as current, with `Password + Authenticator app` |

That fourth row is worth pausing on. Once an authenticator is enrolled, IDEN asks for the code on
**every** sign-in, whatever the application requested — see [Assurance](../concepts/assurance.md).

### Self-service

| Do this | You should see |
|---|---|
| **Profile** → change your display name → Save changes | "Saved." |
| **Security** → change your password | It asks you to confirm your current password first, then reports how many other sessions were signed out |
| **Permissions** | Every permission you hold, each showing where it came from |

That last screen is the one worth looking at twice. It answers *why can this person do that?* — and
it is the same view administrators get for anyone else.

### Administration

| Do this | You should see |
|---|---|
| **APIs** → Register API, then define a scope on it | The scope listed under the API that owns it |
| **Roles** → Create role → tick that scope → Save | The role holding it |
| **Users** → Add user → assign the role | A one-time password, shown once |
| Open that user → **Everything they can do** | The new scope, traced back to the role |
| **Groups** → Create group → give it a role → add the user | The member count rising |
| Re-open the user | The group's role now among their permissions |
| **Clients** → Register client | A secret for a confidential client, nothing for a public one |
| **Audit log** | Every one of the above, newest first, with your name against it |

### The parts that are supposed to refuse

A system that only works when you do the right thing has not been tested.

| Do this | You should see |
|---|---|
| Sign in as the new user, who holds only the `member` role | No **Administration** section at all |
| As that user, open `/console/admin/users` directly | An explanation, not a broken page |
| As an administrator, open **Roles** → `administrator` | Marked built in, and not editable |
| Try to delete an API whose scopes are in use | A refusal naming what still depends on it |
| Try to remove the `administrator` role from your own account | A `409` refusal — you are the last one |
| Enter a wrong password five times quickly | A countdown, not a generic error |

The last three are the ones people skip. The refusals are the product.

---

## Set up your organization

In the order that avoids rework:

1. **[Profile fields](profile-schema.md)** — what you record about people beyond name and email.
   Everyone's profile form is built from this, so define it before you add anyone.
2. **[APIs and scopes](protect-an-api.md)** — register each backend that will trust IDEN, and define
   the permissions it understands.
3. **Roles** — bundle those permissions into job functions. Name them after the job, not after the
   permissions they happen to contain.
4. **Groups** — your departments and teams. Give them roles; membership does the rest.
5. **People** — add them, put them in groups. Direct grants exist for genuine exceptions, not as the
   normal path.
6. **[Your applications](register-a-client.md)** — register each one and choose what it may request.

## Before you let anyone else in

Work through [Before you expose it](../operations/security-checklist.md) in full. The short version:
TLS with `IDEN_ENV=prod`, a proxy doing flood protection, the bootstrap password changed, and the
signing keys backed up somewhere that is not this server.

## Common problems

??? failure "`Permission denied` writing the signing key"
    The image runs as uid 1000 and cannot write into `provider/keys`. On Linux the directory belongs
    either to `root` — if Docker created it for you when the bind mount had nowhere to point — or to
    your own uid if you made it. Neither is 1000.

    Use the `mkdir` and `--user` form in [step 2](#2-generate-a-signing-key), which writes as you and
    sidesteps it. If you have already hit the error and want the shortest way out:

    ```bash
    sudo chown 1000:1000 provider/keys
    ```

    Pick one or the other, not both: `--user` needs the directory owned by **you**, the `chown` needs
    it owned by **1000**. Mixing them reproduces the same error from the other side.

    Simplest of all, if the host has Python and `uv`:

    ```bash
    cd provider && uv run python -m scripts.gen_keys
    ```

??? failure "`Read-only file system: '/keys/iden-....pem'`"
    The generator was run inside the *running* provider — `docker compose ... exec provider python -m
    scripts.gen_keys`. `deploy/docker-compose.yml` mounts the keys `:ro`, deliberately: the provider
    signs with them and never writes them.

    Use the standalone `docker run` in [step 2](#2-generate-a-signing-key), which mounts the
    directory writable, then restart the provider so it picks the key up.

??? failure "`No signing keys in /keys`"
    Step 2 was skipped, or the keys directory did not exist when Docker mounted it — in which case
    Docker helpfully created an empty one. Generate the key, then
    `docker compose -f deploy/docker-compose.yml restart provider`.

??? failure "`No schema found. Run alembic upgrade head first.`"
    The `migrate` service has not finished, or failed. `docker compose -f deploy/docker-compose.yml
    logs migrate` says which. The seed refuses to half-fill a database rather than leaving you with
    one that half-matches the code.

??? failure "The dashboard redirects forever and never signs in"
    The usual cause, and almost always one of three settings not naming the same origin:
    `IDEN_ISSUER`, `IDEN_ALLOWED_ADMIN_ORIGINS`, and the `dashboard` client's redirect URIs. All
    three are compared exactly.

    The browser console names which one — a CORS refusal points at the origin list, an
    `invalid_request` on the redirect points at the client.

??? failure "Signing in works, then the dashboard immediately signs out again"
    Usually the clock. Access tokens live ten minutes, and a container whose time has drifted issues
    tokens that are already expired. Check `date` inside the provider container against the host.

??? failure "`connection refused` on 5432"
    PostgreSQL has not finished starting. `docker compose -f deploy/docker-compose.yml ps` should
    show it healthy before the provider tries.

??? failure "Profile photo upload answers `503`"
    No object store is attached. Either set `IDEN_S3_ENDPOINT_URL` and its credentials, or accept it
    — every other feature works without one.

More in [Troubleshooting](troubleshooting.md).
