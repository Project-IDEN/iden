# Assurance and step-up

"Signed in" is not one thing. Someone who typed a password is less certainly themselves than someone
who typed a password *and* a code from their phone. IDEN reports that difference, and applications
can demand more of it.

## `amr` — what was actually done

The methods used, as a list. IDEN emits:

| Value | Meaning |
|---|---|
| `pwd` | A password |
| `otp` | A time-based code from an authenticator app |
| `face` | Facial recognition — designed for, not yet built |
| `mfa` | Added automatically when two or more distinct factors were used |

## `acr` — how strong that adds up to

A single level, derived from `amr` at the moment a token is issued:

| Level | Reached by |
|---|---|
| `iden:loa:1` | One factor |
| `iden:loa:2` | Two or more factors |
| `iden:loa:3` | Two or more, one of which is a face |

**Derived, never stored.** If someone adds a second factor mid-session, the next token they receive
reports the higher level with no state anywhere to keep in sync.

## An enrolled authenticator is always required

Before any application asks for anything: **once someone has set up an authenticator, a password
alone stops being enough to sign in as them.** IDEN asks for the code on every sign-in, whatever the
client requested.

This is what enrolling means. A second factor that applied only when an application asked for it
would protect nobody — whoever holds the password would simply use an application that does not ask,
and every deployment has one.

Two details follow from it:

- An **unconfirmed** enrollment does not count. A credential exists from the moment someone opens the
  QR code, and treating that as a factor would lock out anyone who walked away from the screen.
- The rule is enforced at `/oauth2/authorize`, not only in the sign-in steps. That endpoint is what
  issues the authorization code, so a session that skipped the code form and returned to the resume
  URL is sent back rather than handed one.

## Demanding more: `acr_values`

An application asks by adding `acr_values=iden:loa:2` to its authorization request. If the session
does not reach that level, IDEN sends the person through the missing step rather than refusing —
they finish where they were going, having proved more on the way.

The missing step is only the method they still owe. Someone already signed in with a password is
asked for the code from their authenticator, not for the password again; `auth_time` stays the time
they signed in, because a step-up adds to a sign-in rather than starting a new one.

Levels are ordered, so a request for `iden:loa:2` is satisfied by a session at `iden:loa:3`.

### A level they cannot reach

If nothing this person has set up reaches the level — `iden:loa:2` from someone with no
authenticator — there is no step to send them through. IDEN returns to your `redirect_uri` with:

```
error=unmet_authentication_requirements
```

This is the error [OpenID Connect defines](https://openid.net/specs/openid-connect-unmet-authentication-requirements-1_0.html)
for exactly this case. The alternative — a code form they have no authenticator to answer — would
leave them stuck on a page with no way off it. What to do instead is your application's decision:
explain what is needed, or send them to set up an authenticator.

Discovery lists only the levels a registered method can reach, so `acr_values_supported` does not
include `iden:loa:3` until something registers a face.

## Demanding freshness: `max_age`

A different question. `acr_values` asks *how strongly* someone proved themselves; `max_age` asks
*how recently*.

They compose: a checkout page might ask for `acr_values=iden:loa:2&max_age=300` — two factors, within
the last five minutes.

## Freshness inside IDEN

IDEN applies this to itself. Changing a password, changing an email address, removing an
authenticator, and signing out another session all require a sign-in within the last five minutes —
not merely a valid token.

The reasoning: someone holding a stolen access token can read a profile, and that is bad. Without
this rule they could also change the password and remove the second factor, and that is
*unrecoverable*. Requiring a recent sign-in sends them back through the one step they cannot
complete.

The refusal follows [RFC 9470](https://www.rfc-editor.org/rfc/rfc9470):

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_user_authentication",
                  error_description="A sign-in within 300s is required", max_age=300
```

An application seeing this should send the person back through `/oauth2/authorize` with that
`max_age`, then retry. The round trip closes because `/authorize` accepts the same parameter.

!!! warning "This only works because access tokens carry `auth_time`"
    Your API never sees the ID token — that belongs to the application. If the sign-in time were only
    in the ID token, no resource server could enforce freshness at all. IDEN puts `auth_time` in
    access tokens for exactly this reason ([RFC 9068 Section 2.2.1](https://www.rfc-editor.org/rfc/rfc9068)).
