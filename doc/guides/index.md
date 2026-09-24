# Guides

Task-shaped instructions. Each assumes you have read the [concepts](../concepts/index.md) it depends
on, and links back where it matters.

## Getting IDEN running

Two paths, depending on what you are doing.

- **[Install it for your organization](install.md)** — the whole system in containers, from a clone
  to a signed-in administrator, with a check on every part before anyone else is let in. About thirty
  minutes.
- **[Run it locally](quickstart.md)** — the server alone, on your own machine, in about five minutes.
  For reading the code, running the tests, or pointing an integration at something you control.
- **[Run the frontends](run-the-frontends.md)** — the development loop for the sign-in page and the
  dashboard themselves.

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
