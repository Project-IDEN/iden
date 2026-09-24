# Validate tokens in your API

Your API validates IDEN's access tokens **offline**. No call to IDEN on the request path, no shared
database, no network hop between your service and identity.

Any language with a JWT library can do this; the steps are the same everywhere.

## 1. Register the API and its permissions

```bash
# The API itself — the audience tokens for it will carry
curl -X POST http://localhost:8000/admin/apis \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "attendance", "audience": "https://api.example.org/attendance"}'

# One permission under it
curl -X POST http://localhost:8000/admin/apis/{id}/scopes \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"value": "attendance:records:read", "description": "View attendance records."}'
```

`description` is required, and it is not paperwork: it is the sentence someone reads on a consent
screen. A permission nobody can describe is one nobody can meaningfully agree to.

## 2. Fetch and cache the signing keys

```
GET /.well-known/openid-configuration   →  jwks_uri
GET /.well-known/jwks.json              →  the public keys
```

Cache them. Refetch when you see a `kid` you do not recognise — that is how key rotation reaches you
without a redeploy.

## 3. Validate every request

```python
import jwt
from jwt import PyJWKClient

jwks = PyJWKClient("http://localhost:8000/.well-known/jwks.json")
AUDIENCE = "https://api.example.org/attendance"
ISSUER = "http://localhost:8000"

def authorize(authorization_header: str, required: str) -> dict:
    token = authorization_header.removeprefix("Bearer ")

    claims = jwt.decode(
        token,
        jwks.get_signing_key_from_jwt(token).key,
        algorithms=["RS256"],
        audience=AUDIENCE,      # not optional — see below
        issuer=ISSUER,
    )

    if required not in claims.get("scope", "").split():
        raise PermissionError(f"missing scope: {required}")

    return claims
```

!!! danger "`audience` is the check people skip"
    Without it, **any** valid IDEN token is accepted — including one issued to a completely different
    service, which its owner may hold legitimately. Checking the signature only proves IDEN wrote it,
    not that IDEN wrote it *for you*.

## 4. Distinguish 401 from 403

| Status | Means | When |
|---|---|---|
| `401` | *Authenticate again.* | Missing, expired, malformed, wrong audience, bad signature |
| `403` | *Authenticating will not help.* | Valid token, insufficient permission |

Collapsing these tells a client to retry a sign-in that cannot fix anything, and hides the real
problem from whoever is debugging.

## Reading claims

| Claim | Use |
|---|---|
| `sub` | Who this is. A user id, or a client id for a machine client. |
| `scope` | Space-delimited permissions. |
| `client_id` | Which application. Useful in your own audit trail. |
| `acr`, `amr` | How strongly they authenticated — see [Assurance](../concepts/assurance.md). |
| `auth_time` | When. Required if you want to demand a *recent* sign-in. |
| `jti` | Unique id. Only needed if you check the denylist. |

## Demanding a recent sign-in

For a destructive endpoint, check `auth_time` yourself and refuse when it is too old:

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_user_authentication", max_age=300
```

A client that understands [RFC 9470](https://www.rfc-editor.org/rfc/rfc9470) will send the person
back through `/oauth2/authorize?max_age=300` and retry.

## If you need instant revocation

Offline validation means a revoked token keeps working until it expires — ten minutes by default.
Usually the right answer is to accept that. If you cannot, call
[`POST /oauth2/introspect`](../reference/endpoints.md), which checks the denylist. It costs a network
round trip on every request, which is the thing offline validation exists to avoid, so use it only
where it earns that cost.

Introspection requires a **confidential** client, and a client may only introspect tokens issued to
itself (RFC 7662 Section 4). A token belonging to someone else comes back `{"active": false}` — the same
answer an unknown token gets, so the endpoint cannot be used to discover what exists. If your API is
a separate client from the one that obtained the token, offline validation is the path open to you.
