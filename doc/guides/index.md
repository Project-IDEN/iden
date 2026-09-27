# Guides

Task-shaped instructions. Each assumes you have read the [concepts](../concepts/index.md) it depends
on, and links back where it matters.

## Getting IDEN running

Four paths. Each is one page with every step, from an empty directory to a signed-in administrator.
[Install IDEN](install.md) compares them.

- **[On a laptop, in Docker](local-docker.md)**: the whole system in containers on `localhost`,
  to try or demo it. About fifteen minutes.
- **[Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md)**: the whole system on the
  internet for your organization, with no inbound port. About an hour.
- **[Run the provider from source](quickstart.md)**: the server alone, for reading the code,
  running the tests, or pointing an integration at it. About five minutes.
- **[Develop the frontends](run-the-frontends.md)**: the provider and both frontends from source,
  for working on the sign-in page and the dashboard.

Then **[After installing](first-steps.md)** checks every part and sets up your organization.

## Integrating an application

Start here if you are connecting something you built to IDEN.

1. **[Register your application](register-a-client.md)** — getting a `client_id`, and the choices
   that are hard to change later.
2. **[Using a standard OIDC library](oidc-libraries.md)** — the configuration for browser apps,
   server-rendered apps, mobile, and backends. Do not hand-roll the protocol.
3. **[Add a web application](web-application.md)** — the flow itself, step by step, if you want to
   see what the library is doing.
4. **[Add a machine client](machine-client.md)** — a backend acting as itself, no person involved.
5. **[Validate tokens in your API](protect-an-api.md)** — the other side, in any language.
6. **[Handle single sign-out](single-sign-out.md)** — so that signing out means something.
7. **[Troubleshooting](troubleshooting.md)** — symptom first, then what IDEN is telling you.

## Administering IDEN

- **[Define your profile schema](profile-schema.md)** — the fields your organization collects about
  people, beyond name and email.

Then [Before you expose it](../operations/security-checklist.md), which is the list to work through
before anyone outside your own machine can reach the deployment.
