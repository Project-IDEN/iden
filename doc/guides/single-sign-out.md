# Handle single sign-out

Signing out of IDEN does not, on its own, sign anyone out of your application. Your application has
its own session — a cookie, a server-side record — and it will keep serving the user until something
tells it not to.

That "something" is a **logout token**, delivered server-to-server when the session ends.

## 1. Register a back-channel URL

```bash
curl -X PATCH http://localhost:8000/admin/clients/{id} \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"backchannelLogoutUri": "https://library.example.org/backchannel-logout"}'
```

Leave it null and your application is never told. That is the behaviour of a client that has not
implemented this yet — not an error, just a gap.

## 2. Remember `sid` at sign-in

The ID token carries a `sid` claim naming the IDEN session. Store it alongside your own session
record. It is what lets you end the *right* one later.

```python
session["iden_sid"] = id_token_claims["sid"]
```

## 3. Accept the logout token

IDEN sends `POST` with `application/x-www-form-urlencoded` and a single `logout_token` field.

```python
@app.post("/backchannel-logout")
def backchannel_logout(logout_token: str = Form(...)):
    claims = jwt.decode(
        logout_token,
        jwks.get_signing_key_from_jwt(logout_token).key,
        algorithms=["RS256"],
        audience=CLIENT_ID,
        issuer=ISSUER,
    )

    # This is what makes it a logout token rather than an ID token.
    if "http://schemas.openid.net/event/backchannel-logout" not in claims.get("events", {}):
        raise HTTPException(400, "not a logout token")

    # An ID token has a nonce. A logout token must not — without this check a
    # replayed logout token could pass as proof that someone just signed in.
    if "nonce" in claims:
        raise HTTPException(400, "logout token must not carry a nonce")

    end_sessions_with(iden_sid=claims["sid"])
    return Response(status_code=200)
```

!!! danger "Validate `events` and the absence of `nonce`"
    Both come from the specification and both exist for the same reason: a logout token is signed by
    the same key as an ID token and carries `sub`, so without these two checks an attacker who
    captured one could replay it as evidence that someone is authenticated.

    IDEN enforces the mirror image — a token carrying `events` is refused as an `id_token_hint`.

## 4. Return quickly

Return `200` as soon as you have ended the session. IDEN's timeout is five seconds and delivery is
**not retried**: an unreachable application will find out at its next token exchange anyway, and a
durable job queue is a dependency this project does not otherwise need.

Every attempt is audited with its outcome, so a sign-out that did not reach you is visible in
`GET /admin/audit` afterwards.

## Sending someone to sign out

```
GET /oauth2/logout
  ?id_token_hint=<the ID token you stored>
  &post_logout_redirect_uri=https://library.example.org/
  &state=<optional>
```

`postLogoutRedirectUri` must be registered on the client, or IDEN returns `204` and goes nowhere —
an unregistered redirect target is an open redirector.

!!! note "A request with no session cookie ends nothing"
    `id_token_hint` says who *was* signed in. It is not a credential for ending someone else's
    session.

## What ending a session actually does

1. Refresh tokens from that session are revoked — nothing new can be minted.
2. A logout token goes to every application that registered a URL **and** was signed into during that
   session. Applications the session never reached are not told.
3. The session and cookie are cleared.

The same happens however the session ends, so your application receives the same logout token in
every case:

- the person signs out, or ends the session from their sessions page;
- someone else signs in on that browser, which holds one account at a time;
- the password is changed or reset — every session except the one making the change;
- an administrator deactivates or deletes the account, or resets its password.

Access tokens already issued run to their expiry. They are self-contained by design, and ten minutes
is the trade that buys offline validation.
