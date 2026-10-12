# IDEN

IDEN is a **self-hosted identity and access control provider**. One organization deploys it, owns
every row in its database, and uses it to answer two questions for every application it runs:

- **Who is this person?** — sign-in, sessions, multi-factor, single sign-on
- **What are they allowed to do?** — permissions defined and assigned at runtime, delivered in tokens

It speaks OpenID Connect, so anything that already knows how to talk to Google or Microsoft can talk
to IDEN without learning anything new.

## Single-organization by design

This is the decision everything else follows from. IDEN is not Auth0, Okta, or Entra ID: there is no
tenant concept, no vendor above your administrators, and no support ticket standing between you and
any change.

| | |
|---|---|
| **You own the data** | Password hashes, audit trails, and face embeddings never leave infrastructure you control. |
| **Your staff are the administrators** | The `admin:*` permissions are unrestricted. There is no higher authority. |
| **No tenant column, anywhere** | Every query is simpler for it, and there is no class of bug where one organization sees another's data, because there is no other organization. |

The trade is that IDEN cannot host two organizations. If you need that, run two deployments.

## Where to start

<div class="grid cards" markdown>

- :material-lightbulb-outline: **[Concepts](concepts/index.md)**

    The mental model, in the order it makes sense. Start here if you are new to
    identity — the vocabulary is the hard part, not the code.

- :material-rocket-launch-outline: **[Guides](guides/index.md)**

    Task-shaped. Integrating something you built? Start at
    [Register your application](guides/register-a-client.md), then
    [Using a standard OIDC library](guides/oidc-libraries.md).

- :material-book-open-variant: **[Reference](reference/index.md)**

    Endpoints, permissions, token claims, settings, the data model, error codes.

- :material-server: **[Operations](operations/index.md)**

    Deploying it, and what must be true before anyone outside your machine can
    reach it.

</div>

## What it supports today

| Capability | Where it stands |
|---|---|
| **Sign-in** | Password, with an authenticator app or a face as a second factor. Faces are enrolled at a kiosk and checked for liveness. |
| **OAuth flows** | Authorization code with PKCE, and client credentials. Nothing else — see [Tokens](concepts/tokens.md#why-only-two-flows). |
| **Single sign-on** | One session across every application, with silent checks, forced re-authentication, and freshness requirements. |
| **Single sign-out** | Ending a session ends it everywhere, via back-channel logout. |
| **Permissions** | Defined at runtime by administrators, assigned to people directly, through roles, or through groups. |
| **Profile fields** | Whatever your organization actually collects — a university and a company need different things. Photos too, given an S3-compatible store. |
| **Audit** | Every state-changing request, permanently. |
| **Two browser apps** | A hosted sign-in page and an administration dashboard, both branded with your organization's name and logo. |

The dashboard and the sign-in page are ordinary OIDC clients of the provider, with no privileged path
of their own — which means the API surface they use is the one you get. Everything they can do,
[your own applications](guides/register-a-client.md) can do.

## What it does not do

Being explicit about this is more useful than a feature list.

- **Federation.** IDEN is the source of truth for identity, not a broker in front of Google or a
  campus SAML server. See [the reasoning](roadmap.md#federation).
- **Multi-tenancy.** By design, as above.
- **Account deletion by the account holder.** In a single-organization deployment the organization
  owns the identity — a student cannot delete their university account.
- **Implicit and password grants.** Both are discouraged by OAuth 2.1 and neither is implemented.
