# Register your application

Every application that talks to IDEN needs a **client** — an identity of its own, separate from the
people who use it. This is the first step for any integration, and the choices here are hard to
change later.

!!! info "Who registers it"
    This page is the administrator's route — `POST /admin/clients`, or the dashboard. It is the only
    way to register a machine-to-machine client, to attach a scope beyond OpenID Connect's own, or
    to skip the consent screen.

    IDEN has no dynamic client registration endpoint, and never registers a client because something
    asked. There is a second, narrower route: an account holding the `developer` role registers its
    own applications through `POST /developer/clients`, which offers the authorization code flow and
    nothing else. See
    [Let people register their own applications](self-service-registration.md).

## Which kind of client are you

The one question everything else follows from: **can your application keep a secret?**

| | Public | Confidential |
|---|---|---|
| Examples | Browser SPA, mobile app, desktop app | Server-rendered web app, backend service, cron job |
| Has a secret | No | Yes |
| Proves itself with | PKCE | Its secret, plus PKCE |
| Can use `client_credentials` | No | Yes |

A secret shipped inside a browser bundle or a mobile binary is not a secret — anyone can extract it.
Register those as **public** and let PKCE do the work. Claiming to be confidential when you are not
does not make you safer; it just means the secret is in a file someone can read.

!!! tip "Server-rendered apps are confidential"
    If your Next.js, Django, or Rails app exchanges the code on the **server**, it is confidential.
    If it exchanges the code in the browser, it is public.

## Registering

```bash
curl -X POST http://localhost:8000/admin/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "library",
    "name": "Library",
    "clientType": "public",
    "allowedGrants": ["authorization_code", "refresh_token"],
    "redirectUris": ["https://library.example.org/callback"],
    "postLogoutRedirectUris": ["https://library.example.org/"],
    "backchannelLogoutUri": "https://library.example.org/backchannel-logout",
    "skipConsent": false,
    "grantableScopeIds": ["<scope uuid>"]
  }'
```

### The fields that matter

**`clientId`** — the public name of your application. It appears in tokens and in the audit log.
Stable; choose something you will still recognise.

**`allowedGrants`** — include `refresh_token` if you want long-lived sessions without repeated
sign-ins. That is only half of it: your application must also request the **`offline_access`** scope
at `/authorize`. The grant says what this client is permitted to do; the scope says what a particular
request asked for and the person agreed to (OIDC Core Section 11).

**`redirectUris`** — where IDEN sends the person back. Matched **exactly**: not a prefix, not a
pattern, not ignoring the query string.

**`grantableScopeIds`** — what your application may *request*. It still only receives what the person
actually holds; this is a ceiling, not a grant.

**`skipConsent`** — `true` only for applications the organization itself owns. See
[Consent](../concepts/consent.md).

**`backchannelLogoutUri`** — where IDEN tells you a session ended. Leave it out and your application
keeps its own session alive after the person signs out elsewhere. See
[Handle single sign-out](single-sign-out.md).

## Redirect URIs in practice

Exact matching is the rule that catches people out, so:

=== "Web"

    ```
    https://library.example.org/callback
    ```

    Not `https://library.example.org/callback/`. Not `https://library.example.org`. The string your
    library sends must be the string that is registered, character for character.

=== "Mobile / desktop"

    ```
    com.example.library://callback
    ```

    A custom scheme is fine — the validator requires an absolute URI, not an `https` one. Register
    the exact scheme your app claims.

=== "Local development"

    ```
    http://localhost:5173/callback
    ```

    Register development URIs on a **separate client** from production. Mixing them means a
    misconfigured dev build can receive codes meant for the real application.

!!! warning "Native apps using an ephemeral loopback port"
    [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252) suggests native apps listen on
    `http://127.0.0.1:{random}/callback` and lets the provider ignore the port. **IDEN matches
    exactly**, so a random port will not match.

    Register a fixed port, or use a custom scheme. This is a deliberate trade — a permissive
    comparison is how authorization codes get exfiltrated — but it is a real constraint if you are
    porting an app that relies on it.

## One client per application, per environment

Do not share a client between your web app and your mobile app, or between staging and production.

- Their redirect URIs differ, and sharing means each accepts the other's.
- Revoking or rotating one should not affect the other.
- The audit log attributes actions to a `client_id`. Shared clients make that meaningless.

## Client secrets

Returned **once**, on creation, and hashed immediately. IDEN cannot show it to you again.

```bash
# Rotate — the new secret is returned once, the old stops working immediately
curl -X POST http://localhost:8000/admin/clients/{id}/rotate-secret \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

If you cannot tolerate a gap during rotation, register a second client, migrate to it, then retire
the first. That has no gap at all.

## Next

- [Add a web application](web-application.md) — the flow itself, step by step
- [Using a standard OIDC library](oidc-libraries.md) — the configuration for common stacks
- [Add a machine client](machine-client.md) — no person involved
