# Add a machine client

For a backend that acts **as itself** — a nightly job, a service calling another service.
No person is involved, so there is nobody to redirect and nothing to consent to. (Face enrolment
kiosks are machine clients too, but they are registered and paired under
[Kiosks](../operations/kiosks.md), not here.)

!!! tip "Prefer the dashboard?"
    Registering one is also in the dashboard, under **Administration → Clients**. `$ADMIN_TOKEN`
    in the examples is an administrator's access token — [how to get
    one](index.md#calling-the-admin-api-yourself).

## Register it

```bash
curl -X POST http://localhost:8000/admin/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "clientId": "attendance-sync",
    "name": "Attendance sync job",
    "clientType": "confidential",
    "allowedGrants": ["client_credentials"],
    "grantedScopeIds": ["<scope uuid>"]
  }'
```

Two things differ from a [web application](web-application.md):

- **`confidential`.** A machine client must keep a secret, so it must be able to. Anything running in
  a browser cannot, which is why public clients are refused this flow entirely.
- **`grantedScopeIds`, not `grantableScopeIds`.** These are permissions the client **holds in its own
  right**, not ones it may request on someone's behalf. The distinction is the whole difference
  between the two flows.

The response contains `clientSecret`, shown **once**.

## Get a token

```bash
curl -X POST http://localhost:8000/oauth2/token \
  -u attendance-sync:$CLIENT_SECRET \
  -d grant_type=client_credentials \
  -d scope="attendance:records:write"
```

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 600,
  "scope": "attendance:records:write"
}
```

**No refresh token and no ID token.** There is no session to keep alive and no person to describe —
when the token expires, ask again. That is cheaper than managing rotation.

The `sub` of the token is the client itself, not a person. Your API should expect that: audit
entries attributed to `attendance-sync` are correct, not a bug.

## Rotating the secret

```bash
curl -X POST http://localhost:8000/admin/clients/{id}/rotate-secret \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The new secret is returned once and the old one stops working immediately. Deploy the new one first
if you cannot tolerate a gap — or register a second client and retire the first, which has no gap at
all.

!!! tip "Basic or POST body, your choice"
    `-u client:secret` sends HTTP Basic, which takes precedence. `client_id` and `client_secret` in
    the form body work too. Basic keeps the secret out of anything that logs request bodies.
