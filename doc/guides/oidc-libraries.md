# Using a standard OIDC library

IDEN is a conforming OpenID Connect provider, so the right way to integrate is a library that already
knows the protocol. Do not hand-roll the flow: PKCE, `state`, `nonce`, token validation, and clock
skew are all things a maintained library already gets right.

## What every library needs

Almost all of them ask for the same four things:

| Setting | Value |
|---|---|
| **Issuer / authority** | `https://iden.example.org` — your `IDEN_ISSUER` |
| **Discovery URL** | `https://iden.example.org/.well-known/openid-configuration` |
| **Client ID** | From [registration](register-a-client.md) |
| **Scopes** | `openid profile email` plus whatever your APIs need |

Point the library at the **discovery URL** and it configures everything else itself — endpoints,
signing keys, supported algorithms. Never hardcode endpoint paths; they come from that document.

## What IDEN supports

Set these explicitly if your library asks:

| Setting | IDEN |
|---|---|
| Response type | `code` — nothing else |
| PKCE | **Required**, `S256`. Not optional, even for confidential clients. |
| Client auth | `client_secret_basic`, `client_secret_post`, or `none` for public clients |
| ID token signing | `RS256` |
| Refresh tokens | Request the **`offline_access`** scope (OIDC Core Section 11). The client must also allow the `refresh_token` grant — the grant is what it *may* do, the scope is what this request asked for. Ask for neither and you get no refresh token. |
| Front-channel logout | Not supported — use [back-channel](single-sign-out.md) |

## Browser single-page app

Public client, PKCE, tokens in memory.

=== "oidc-client-ts"

    ```ts
    import { UserManager, WebStorageStateStore } from "oidc-client-ts";

    export const auth = new UserManager({
      authority: "https://iden.example.org",
      client_id: "library",
      redirect_uri: "https://library.example.org/callback",
      post_logout_redirect_uri: "https://library.example.org/",
      response_type: "code",
      scope: "openid profile email offline_access library:loans:read",

      // Silent renewal in a hidden iframe. This is what `prompt=none` exists for.
      automaticSilentRenew: true,
      silent_redirect_uri: "https://library.example.org/silent-renew",

      // Session state, not tokens. Tokens stay in memory — anything in
      // localStorage is readable by any script on the page.
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    });
    ```

=== "react-oidc-context"

    ```tsx
    import { AuthProvider } from "react-oidc-context";

    <AuthProvider
      authority="https://iden.example.org"
      client_id="library"
      redirect_uri="https://library.example.org/callback"
      scope="openid profile email offline_access library:loans:read"
      onSigninCallback={() => window.history.replaceState({}, "", "/")}
    >
      <App />
    </AuthProvider>
    ```

=== "angular-auth-oidc-client"

    ```ts
    provideAuth({
      config: {
        authority: "https://iden.example.org",
        clientId: "library",
        redirectUrl: "https://library.example.org/callback",
        scope: "openid profile email offline_access library:loans:read",
        responseType: "code",
        silentRenew: true,
        useRefreshToken: true,
      },
    })
    ```

!!! warning "Silent renewal needs the session cookie"
    `prompt=none` in an iframe works because the browser sends IDEN's session cookie. That cookie is
    `SameSite=Lax`, which permits it on a top-level navigation but **not** on a cross-site iframe
    request.

    In practice this means silent renewal works when IDEN and your app share a site, and does not
    when they are cross-site in a browser that blocks third-party cookies. If they are cross-site,
    use refresh tokens instead of iframe renewal — which means requesting `offline_access`.

## Server-rendered web app

Confidential client. The code exchange happens on the server and the tokens never reach the browser.

=== "Auth.js (Next.js)"

    ```ts
    import NextAuth from "next-auth";

    export const { handlers, auth } = NextAuth({
      providers: [{
        id: "iden",
        name: "IDEN",
        type: "oidc",
        issuer: "https://iden.example.org",
        clientId: process.env.IDEN_CLIENT_ID,
        clientSecret: process.env.IDEN_CLIENT_SECRET,
        authorization: { params: { scope: "openid profile email" } },
        checks: ["pkce", "state", "nonce"],
      }],
    });
    ```

=== "Authlib (FastAPI / Flask)"

    ```python
    import os

    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="iden",
        server_metadata_url="https://iden.example.org/.well-known/openid-configuration",
        client_id=os.environ["IDEN_CLIENT_ID"],
        client_secret=os.environ["IDEN_CLIENT_SECRET"],
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",   # PKCE is mandatory
        },
    )

    @app.get("/login")
    async def login(request: Request):
        return await oauth.iden.authorize_redirect(request, REDIRECT_URI)

    @app.get("/callback")
    async def callback(request: Request):
        token = await oauth.iden.authorize_access_token(request)
        return token["userinfo"]      # already validated by Authlib
    ```

=== "Spring Security"

    ```yaml
    spring:
      security:
        oauth2:
          client:
            provider:
              iden:
                issuer-uri: https://iden.example.org
            registration:
              iden:
                client-id: ${IDEN_CLIENT_ID}
                client-secret: ${IDEN_CLIENT_SECRET}
                scope: openid,profile,email
                authorization-grant-type: authorization_code
    ```

## Mobile and desktop

Public client, PKCE, and the system browser — never an embedded web view. An embedded view can read
the password, which is the thing an identity provider exists to prevent, and it cannot see the IDEN
session cookie, so single sign-on does not work in it.

**AppAuth** ([iOS](https://github.com/openid/AppAuth-iOS),
[Android](https://github.com/openid/AppAuth-Android)) is the reference implementation and handles the
platform details.

Register a custom scheme (`com.example.library://callback`) or a fixed loopback port — see
[the note on ephemeral ports](register-a-client.md#redirect-uris-in-practice).

## Backend service, no user

Client credentials. Most OAuth libraries have a two-line helper; the flow is simple enough to do
directly.

```python
import os

import httpx

response = httpx.post(
    "https://iden.example.org/oauth2/token",
    auth=("attendance-sync", os.environ["CLIENT_SECRET"]),
    data={"grant_type": "client_credentials", "scope": "attendance:records:write"},
)
access_token = response.json()["access_token"]
```

Cache the token until shortly before it expires. There is no refresh token — when it expires, ask
again. See [Add a machine client](machine-client.md).

## Validating tokens in your API

Different job, different library — a JWT validator, not an OIDC client. See
[Validate tokens in your API](protect-an-api.md).

## Testing against a local IDEN

Point the library at `http://localhost:8000` and register a client with your local redirect URI.

Two things differ from production and will surprise you otherwise:

- **`IDEN_ENV=dev` means the session cookie is not `Secure`**, so plain HTTP works. In production it
  is, and a cookie will silently not be sent over HTTP.
- **The signing keys are local.** Tokens from your development IDEN do not validate against a
  production one, which is the point.
