# Errors

Two shapes, because two audiences.

## IDEN's own shape

Everywhere except the OAuth endpoints:

```json
{
  "code": "field_not_writable",
  "message": "This field belongs to the organization, not to you. An administrator sets it.",
  "details": {"field": "student_id"}
}
```

`code` is stable and safe to branch on. `message` is written for a person and may change.

Every refusal outside `/oauth2/*` uses it — including the ones that come from the framework rather
than from a route. A missing token, an unrouted path, and a malformed body all arrive in this shape.
A validation failure names the fields:

```json
{
  "code": "validation_error",
  "message": "The request is invalid.",
  "details": {"fields": [{"field": "body.audience", "message": "Field required"}]}
}
```

## The OAuth shape

`/oauth2/token`, `/revoke`, `/introspect`, and error redirects from `/authorize` use the format fixed
by [RFC 6749 Section 5.2](https://www.rfc-editor.org/rfc/rfc6749#section-5.2), because a client library will
not understand anything else:

```json
{"error": "invalid_grant", "error_description": "Unknown or expired refresh token."}
```

A malformed request to these endpoints — a missing `grant_type`, say — comes back as
`invalid_request` in the same shape, never as IDEN's validation error. A client library reading
Section 5.2 has no way to read anything else.

Errors from `/authorize` arrive as query parameters on your redirect URI, not as a response body —
unless `client_id` or `redirect_uri` was itself invalid, in which case IDEN answers with JSON rather
than redirecting somewhere it has not verified.

## Statuses

| Status | Means |
|---|---|
| `400` | Malformed, or an invalid grant. |
| `401` | *Authenticate again* — missing, expired, revoked, or wrong-audience token. |
| `403` | *Authenticating will not help* — a valid token without the permission. Also freshness refusals, the delegation refusals `cannot_delegate` and `cannot_administer`, and a client change by anyone short of a full administrator. |
| `404` | No such thing. |
| `409` | Conflicts with what exists — a name taken, or a system row that cannot be changed. |
| `413` | The request body is larger than the endpoint accepts — `payload_too_large`. |
| `422` | The request was understood and is not acceptable. |
| `429` | Rate limited. `Retry-After` says how long. |
| `501` | Face sign-in on a deployment without the biometric module. |
| `503` | The request itself was fine, and something it needs is not there. PostgreSQL or Redis is unreachable — then `Retry-After` says when to try again. Or the deployment cannot reach, or does not have, what this feature needs: the biometric engine (`engine_unavailable`), or file storage for photos and logos. |

The `401`/`403` distinction is deliberate everywhere. Collapsing them tells a client to retry a
sign-in that cannot fix anything.

## Two refusals worth recognising

**Step-up required** — the token is valid but the sign-in is too old:

```http
HTTP/1.1 403 Forbidden
WWW-Authenticate: Bearer error="insufficient_user_authentication", max_age=300
```

Send the person through `/oauth2/authorize` with that `max_age` and retry.
[RFC 9470](https://www.rfc-editor.org/rfc/rfc9470).

**Silent check failed** — `prompt=none` could not be satisfied, returned to your redirect URI:

| `error` | Meaning |
|---|---|
| `login_required` | Not signed in, or the session no longer satisfies what you asked |
| `consent_required` | Signed in, has not agreed to these permissions |

## Face captures

What the face routes answer, and what a screen should do about each.

| Code | Status | Means |
|---|---|---|
| `poor_capture` | 422 | Nothing was decided: the picture was not good enough to judge. `details.reasons` says what to fix — `no_face`, `multiple_faces`, `too_small`, `blurred`, `too_dark`, `too_bright`, `off_angle`, `out_of_frame`. Not a failed attempt. |
| `face_rejected` | 401 | At sign-in: not live, or not this person. Deliberately not said which. One of three tries in fifteen minutes: `details.attemptsLeft` says how many remain, and on the last `details.retryAfter` says when face sign-in opens again. |
| `not_live` | 422 | At a kiosk: the capture failed liveness. `details.failed` names the checks. The kiosk is supervised, so it is told. |
| `consent_required` | 422 | At a kiosk: the enrolment did not carry the person's agreement to the current consent text. The kiosk asks again. |
| `invalid_frames` | 422 | The frames do not match the challenge — wrong count, not JPEG, or too large. |
| `face_challenge_invalid` | 404 | The capture's challenge expired or was used. Fetch a new one. |
| `enrolment_ticket_invalid` | 404 | The kiosk ticket expired, was used, was replaced, or ran out of attempts. |
| `kiosk_out_of_service` | 403 | The kiosk has been switched out of service in the dashboard. |
| `pairing_code_invalid` | 404 | The kiosk pairing code expired, was used, or was replaced by a newer one. |
| `kiosk_managed` | 409 | From `/admin/clients`: this client belongs to a kiosk. Change it at `/admin/kiosks`. |
| `face_not_enrolled` | 404 | There is no face on this account to compare against. |
| `face_enrolment_outdated` | 409 | The face was enrolled under an earlier model. Enrol again, or an administrator re-embeds. |
