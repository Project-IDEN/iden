# Install IDEN

There are four ways to run IDEN. Pick one. Each page has every step from an empty directory to a
signed-in administrator, so you won't need another page open while you follow it.

| You want to | Follow | Runs | Time |
|---|---|---|---|
| Try the whole system, or demo it, on your own machine | **[On a laptop, in Docker](local-docker.md)** | Everything in containers, on `localhost` | 15 min |
| Put it on the internet for your organization | **[Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md)** | Everything in containers, behind nginx and `cloudflared`, with no inbound port | 1 hour |
| Work on the provider, or point an integration at it | **[Run the provider from source](quickstart.md)** | The provider on your machine, its stores in Docker | 5 min |
| Work on the sign-in page or the dashboard | **[Develop the frontends](run-the-frontends.md)** | The provider and both frontends on your machine, the stores in Docker | 10 min |

Once you can sign in, **[After installing](first-steps.md)** checks every part of the system and
walks through setting up your organization. The steps there are the same whichever way you installed.

## What gets installed

The two container paths run seven services. The two source paths run the first three from your
checkout and put only the stores in Docker.

| Service | Port | What it is |
|---|---|---|
| **provider** | 8000 | The application: OIDC, administration, and self-service in one process. |
| **auth-ui** | 4000 | The hosted sign-in page, served under `/auth`. The only place a password is typed. |
| **dashboard** | 3000 | Administration and self-service, served under `/console`. What each person sees depends on their permissions. |
| **PostgreSQL 18** | 5432 | People, permissions, clients, tokens. The data that matters. |
| **Redis 8** | 6379 | Sessions, pending sign-ins, the token denylist, rate-limit counters. |
| **SeaweedFS** | 8333 | S3-compatible storage for profile photos. Optional. |
| **migrate** | | Runs the database migrations to completion, then exits. It is a separate service so that two provider replicas never migrate the same database at the same time. |

The tunnel path adds two more: **nginx**, which puts the three applications on one origin, and
**cloudflared**, which carries traffic in from Cloudflare.

One deployment serves **one organization**. There is no tenant concept anywhere, and your own staff
are the administrators rather than a vendor's. See [Single-organization by design](../index.md).

## Deploying without Cloudflare

The tunnel is the arrangement that has been written down and tested end to end. Terminating TLS on
your own proxy works too. Use `deploy/nginx/iden.conf.example` for the routing, add a
`listen 443 ssl` block with your certificates, and read [Deployment](../operations/deployment.md#behind-a-proxy)
for what the proxy has to do. The steps otherwise match the tunnel page, minus the Cloudflare
sections.
