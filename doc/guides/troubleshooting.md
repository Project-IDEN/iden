# Troubleshooting an integration

Symptom first, then what IDEN is actually telling you.

## At the authorization endpoint

??? failure "`400` with `invalid_request: redirect_uri is not registered for this client`"
    The URI your library sent is not character-for-character one of the registered ones. Matching is
    exact — no prefix, no pattern, no ignoring a trailing slash.

    Compare the two strings literally. The usual culprits are a trailing `/`, `http` versus `https`,
    and a port that is present in one and not the other.

    This error arrives as **JSON, not a redirect**. Before `client_id` and `redirect_uri` are
    validated, the URI is unverified, and redirecting to it would make IDEN an open redirector.

??? failure "`400` with `invalid_client: Unknown client`"
    The `client_id` does not exist. Also arrives as JSON, for the same reason.

??? failure "`invalid_request: code_challenge is required — IDEN mandates PKCE`"
    Your library did not send PKCE. Most support it and some leave it off by default for
    confidential clients, on the assumption that the secret is enough. IDEN requires it from
    everyone — enable it explicitly (`code_challenge_method: S256`).

??? failure "Redirected back with `error=login_required` and you expected a code"
    You sent `prompt=none` and there was no usable session. That is the endpoint working: it is how
    an application asks *silently* whether someone is still signed in.

    If it happens when you did not expect it, the session exists but does not satisfy what you asked
    for — usually `max_age` has elapsed, or an `acr_values` you requested is not met.

    Without `prompt=none`, it means you sent an `id_token_hint` naming one person and someone else
    signed in. IDEN will not hand you a code for a person you did not ask about, and asking again
    would only show them the same form.

??? failure "`error=unmet_authentication_requirements`"
    You sent an `acr_values` this person has no way to reach — usually `iden:loa:2` from someone who
    has not set up an authenticator. IDEN refuses rather than showing a code form they could not
    answer. Tell them what is needed, or send them to set one up and try again. See
    [Assurance and step-up](../concepts/assurance.md#a-level-they-cannot-reach).

??? failure "`error=consent_required`"
    `prompt=none` again, but the person has not agreed to these permissions. Repeat the request
    without `prompt=none` so they can be asked.

??? failure "Silent renewal in an iframe never completes"
    The session cookie is `SameSite=Lax`, which browsers do not send on a cross-site iframe request.
    If IDEN and your app are on different sites, iframe renewal cannot work — use refresh tokens.

## At the token endpoint

??? failure "`400` with `invalid_grant: Unknown authorization code`"
    Three common causes, in order of likelihood:

    1. **Already used.** Codes are single use. A double-submitting callback route or a React effect
       running twice in development will do this.
    2. **Expired.** They live 60 seconds.
    3. **Wrong client.** The code was issued to a different `client_id`.

??? failure "`invalid_grant` mentioning PKCE"
    The `code_verifier` does not match the `code_challenge` sent earlier. Usually the verifier was
    lost between the two requests — a new browser tab, a server restart with in-memory state, or two
    parallel sign-in attempts overwriting each other's.

??? failure "`400` with `invalid_grant: Refresh token reuse detected`"
    A refresh token was presented after it had already been spent, outside the 30-second grace
    window. The whole family is revoked and the person must sign in again.

    Almost always a storage bug: you kept the old token after rotation. **Every** refresh returns a
    new refresh token, and the old one is dead. Store the new one before you use it.

    See [refresh rotation](../concepts/tokens.md#the-honest-double-use-problem).

??? failure "`401` with `invalid_client`"
    - A confidential client sent the wrong secret, or none.
    - A **public** client sent a secret. IDEN refuses that: a public client that presents a secret is
      either misconfigured or pretending, and neither should be accepted quietly.

??? failure "`400` with `unauthorized_client`"
    The client exists but is not allowed this grant. Check `allowedGrants` — a client without
    `refresh_token` will never receive one, and a public client cannot use `client_credentials` at
    all.

??? failure "`429` with a `Retry-After` header"
    Rate limited. Wait the number of seconds it gives you.

    If this happens in normal use, something is retrying in a loop — a failed refresh being retried
    immediately is the usual shape.

## In your API

??? failure "Every token is rejected as having an invalid audience"
    The `aud` your validator expects is not the audience of the permissions in the token. `aud` comes
    from the **API that owns the scope**, not from the client and not from the issuer.

    Check the API's registered `audience` in `/admin/apis`, and make sure the application is
    requesting scopes that belong to it.

??? failure "Tokens validate but carry none of the permissions you asked for"
    Permissions are pruned silently, and there are three possible reasons:

    1. The **person** does not hold it — check `GET /admin/users/{id}/effective-scopes`.
    2. The **client** may not request it — check `grantableScopeIds`.
    3. It does not exist.

    Silent pruning is deliberate: failing the whole sign-in because an application asked for one
    optional extra would lock out everyone who lacks it.

??? failure "`Unknown kid` when validating"
    A signing key rotated and your cached JWKS is stale. Refetch on an unrecognised `kid` — that is
    how rotation is meant to reach you.

??? failure "A revoked token keeps working"
    Access tokens are self-contained and live ten minutes; IDEN cannot recall one. That is the trade
    that lets you validate without calling IDEN. For immediate revocation use introspection, which
    checks the denylist, on the endpoints where the round trip earns itself.

## Sessions and sign-out

??? failure "Signing out of IDEN leaves your app signed in"
    Expected, unless you implemented the receiving end. Register a `backchannelLogoutUri` and end
    your own session when a logout token arrives —
    [Handle single sign-out](single-sign-out.md).

??? failure "`GET /oauth2/logout` returns `204` instead of redirecting"
    `post_logout_redirect_uri` is not registered for the client IDEN resolved. Add it to
    `postLogoutRedirectUris`, and pass `client_id` or `id_token_hint` so IDEN knows which client you
    mean.

??? failure "A password change signed someone out everywhere"
    Deliberate. A credential change that leaves the old sessions alive has not taken effect. The
    session that made the change survives; every other one ends.

## Still stuck

Two places to look before anything else:

- **`GET /.well-known/openid-configuration`** on the deployment you are hitting. It is generated
  live, so it settles arguments about which endpoints and algorithms exist.
- **`GET /admin/audit`**, filtered by `action`. Every state-changing request is there with its status
  code — including the refusals, which is usually the thing you are trying to explain.
