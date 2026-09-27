# Add a web application

The authorization code flow with PKCE, end to end. This is the flow for anything with a person in
front of it: a single-page app, a server-rendered site, a mobile app.

## 1. Register the client

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
    "grantableScopeIds": ["<scope uuid>", "..."]
  }'
```

| Choice | Guidance |
|---|---|
| `clientType` | `public` for anything running in a browser or on a phone — it cannot keep a secret, and PKCE is what protects it. `confidential` only for a backend. |
| `redirectUris` | Matched **exactly**. No wildcards, no prefix matching. |
| `skipConsent` | `true` only for applications your organization owns. See [Consent](../concepts/consent.md). |
| `grantableScopeIds` | What this application may *request*. It still only receives what the person actually holds. |

## 2. Send the person to IDEN

Generate a PKCE pair — a random `code_verifier`, and its SHA-256 hash, base64url-encoded without
padding, as the `code_challenge`.

```
GET /oauth2/authorize
  ?response_type=code
  &client_id=library
  &redirect_uri=https://library.example.org/callback
  &scope=openid profile email offline_access library:loans:read
  &state=<random, tied to this browser session>
  &nonce=<random, checked in the ID token later>
  &code_challenge=<the hash>
  &code_challenge_method=S256
```

!!! danger "`state` is not optional"
    It is what ties the response back to the request *this browser* started. Without checking it,
    an attacker can hand a victim's browser their own authorization code and have the victim's
    account linked to it. Generate it randomly, store it against the session, and compare on return.

IDEN either redirects straight back with a code — that is [single sign-on](../concepts/sessions.md)
— or sends the person to the sign-in page first.

## 3. Exchange the code

```bash
curl -X POST http://localhost:8000/oauth2/token \
  -d grant_type=authorization_code \
  -d code=$CODE \
  -d redirect_uri=https://library.example.org/callback \
  -d code_verifier=$VERIFIER \
  -d client_id=library
```

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 600,
  "scope": "openid profile email offline_access library:loans:read",
  "refresh_token": "3sT...",
  "id_token": "eyJ..."
}
```

The code is single use and lives 60 seconds. Presenting it twice fails — and IDEN locks the row while
redeeming it, so two simultaneous attempts cannot both succeed.

## 4. Validate the ID token

Before trusting anything in it:

| Check | Why |
|---|---|
| Signature, against JWKS | Otherwise anyone can write one |
| `iss` matches your IDEN issuer | Otherwise another provider's token is accepted |
| `aud` equals your `client_id` | Otherwise a token for a different application is accepted |
| `nonce` matches what you sent | Ties it to *your* request |
| `exp` is in the future | — |

Then read `sub` — the stable identifier for this person. Not the email; people change those.

Store `sid` too, if you plan to support [single sign-out](single-sign-out.md).

## 5. Call APIs with the access token

```
Authorization: Bearer eyJ...
```

Never send the ID token instead. See [Protect an API](protect-an-api.md) for the other side.

## 6. Refresh before it expires

```bash
curl -X POST http://localhost:8000/oauth2/token \
  -d grant_type=refresh_token \
  -d refresh_token=$REFRESH \
  -d client_id=library
```

You get a **new refresh token**. Store it and discard the old one — reusing a spent token is treated
as theft after the [grace window](../concepts/tokens.md#the-honest-double-use-problem).

## Checking silently whether someone is still signed in

For a single-page app, repeat step 2 in a hidden iframe with `prompt=none`. Either a code comes back,
or an error does — nothing is ever shown to the user.

```
GET /oauth2/authorize?...&prompt=none
```

| Error | Meaning |
|---|---|
| `login_required` | Not signed in, or the session no longer satisfies what you asked for |
| `consent_required` | Signed in, but has not agreed to these permissions |
| `account_selection_required` | Needs to choose an account |

## Demanding a fresh sign-in

For a sensitive screen, add `max_age=300` — or `prompt=login` to force it outright. See
[Assurance](../concepts/assurance.md).

## Mistakes worth avoiding

!!! failure "Sending the access token to your own frontend as proof of identity"
    It says what may be done, not who is doing it. Use the ID token.

!!! failure "Skipping `state` because PKCE is enabled"
    They defend against different things. PKCE stops a stolen code being exchanged; `state` stops a
    code being *injected* into your callback.

!!! failure "Storing tokens in `localStorage`"
    Any script on the page can read them. Prefer memory plus a short refresh, or a backend that holds
    them.

!!! failure "Treating `email` or `preferred_username` as the identifier"
    IDEN fixes an address when the account is created, but a username can be renamed, and an
    address can be reused by someone else after the account is deleted. `sub` never changes and
    is never reused.
