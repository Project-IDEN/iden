# The audit log

For an access control system, "who granted which permission to whom, and when" is not a nice-to-have.
It is the question the system exists to be able to answer, and it is the one thing that cannot be
added later — history not written is simply gone.

Every state-changing request writes one row. There is no way to turn it off, and no endpoint that
writes to it: the request being recorded is its only author.

## What counts as state-changing

Any non-`GET` request to `/admin/*`, `/entity/*`, `/developer/*`, `/biometric/*`, `/api/v1/auth/*`,
or `/oauth2/revoke` — plus `GET /oauth2/logout`, which is a `GET` by specification and still destroys
a session.

Reads are not recorded. An audit log nobody can read through is one nobody reads, and `GET` volume
would bury the writes.

Two writes are deliberately excluded because they are routine. `POST /oauth2/token`: a refresh
happens every few minutes for every active session, and the sign-in that authorised it is already in
the log. And a kiosk's heartbeat, sent every minute; its last report is on the kiosk's page in the
dashboard.

## What a row holds

| Field | Notes |
|---|---|
| `action` | Method plus **route template** — `POST /admin/users/{user_id}/roles`. The template groups; the resolved path would not. |
| `target` | The object acted on, taken from the path. |
| `statusCode` | Refused attempts are recorded too. A wall of `403`s from one actor is the signal you want. |
| `actorUserId`, `actorLabel`, `actorClient` | Who, by id, by email *at the time*, and through which application. |
| `ip` | The socket address. `X-Forwarded-For` is recorded in the detail but not trusted — a header the caller sets is a claim, not an observation. |
| `detail` | The request body with secrets removed, plus path parameters. |

## Two design points

**Deleting a user does not erase what they did.** The actor reference is nulled rather than cascaded,
and their email is copied onto each row at the time it is written. After the account is gone, that
label is all that is left of who this was — and it is enough.

**Secrets never reach a row.** Keys named `password`, `clientSecret`, `token`, `code`,
`codeVerifier`, a face enrolment `ticket`, and their relatives are replaced before the row is built, compared with punctuation
stripped so `client_secret` and `clientSecret` are the same key.

## Reading it

`GET /admin/audit` under `admin:audit:read`, newest first, filtered by actor, action substring, and a
time range. There is no write scope, because there is nothing to write.

!!! warning "One known gap"
    The row is written just after the change, from a separate transaction — so if the database
    becomes unreachable in between, the change stands and the record is lost. The failure is logged
    loudly rather than swallowed. Tracked as KI-17 on the [roadmap](../roadmap.md).
