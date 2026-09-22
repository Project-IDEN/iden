# Let people register their own applications

You want other people — a class, a hackathon, a showcase — to put **Continue with IDEN** in their
own apps, without handing any of them the keys to your directory.

That is what the `developer` role is for. It is the equivalent of what a developer can do in Google
Cloud Console for *Sign in with Google*: create your own OAuth client, set your own redirect URIs,
read your own client ID, rotate your own secret. Nothing else.

## What you are handing out

Someone with the `developer` role can, at `/developer/clients` or on the dashboard's **Applications**
screen:

- register an application and receive a generated `client_id`
- choose whether it is public (browser, mobile) or confidential (server-side)
- set and change its redirect URIs
- rotate its secret, and delete it

What they **cannot** do, by construction rather than by policy:

| | Why not |
|---|---|
| Choose their own `client_id` | The first person to ask would take `dashboard`, or a name that reads like another team's app on the consent screen. IDEN generates it. |
| Use the `client_credentials` grant | It is the grant that acts with no user present. A self-registered client that could hold it could mint a token for itself. |
| Attach any scope | Their app gets `openid`, `profile`, `email`, and `offline_access` — which is everything sign-in needs. Anything beyond them is your decision, through `/admin/clients`. |
| Skip the consent screen | A third-party application asks. `skipConsent` exists for your own dashboard. |
| Set a back-channel logout URI | It would make IDEN send an HTTP request to an address a stranger chose. Set it for them if they need single sign-out. |
| See, change, or delete anyone else's application | Every route filters on the owner. Someone else's id answers `404`, which does not even confirm it exists. |

They also cannot see your users, roles, groups, or audit log: the role carries no `admin:` scope, and
their token is not even issued for the `admin` audience.

## Granting it

The `developer` role is seeded with the catalogue. For a handful of people, assign it directly:

```bash
curl -X PUT http://localhost:8000/admin/users/$USER_ID/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"roleIds": ["'$DEVELOPER_ROLE_ID'"]}'
```

That call **replaces** the person's whole set of roles. `developer` already carries every
self-service scope `member` does, so a participant holding only that role loses nothing.

For a cohort, make a group — `Showcase 2026` — give the group the role, and add people to the group.
Removing the group at the end of the event takes the capability back from everyone at once, and
leaves their applications in place for an administrator to clean up.

## What they do next

Everything they need is on their application's page: the issuer, the client ID, and the scopes they
may ask for. Point them at [Using a standard OIDC library](oidc-libraries.md) — from IDEN's side a
self-registered application is an ordinary confidential or public client, so every library works
without special cases.

## Limits worth knowing

- **`IDEN_DEVELOPER_MAX_CLIENTS`** (default `5`) caps how many applications one account may register.
  One participant cannot fill the clients table, and the cap is exact: registrations by one person
  are serialized, so two at once cannot both slip past it.
- **Redirect URIs** must be `https://` anywhere, `http://` on `localhost` or `127.0.0.1`, or a
  reverse-DNS private-use scheme for a native app (`com.example.app:/callback`, RFC 8252). No
  wildcards, no fragments, no credentials in the authority. At most five per application.
- **Everything is audited.** `/developer/*` is covered by the audit middleware, so every
  registration, change, rotation, and deletion is a row in the audit log with the person's name on
  it.
- **An administrator still sees everything.** Self-registered applications appear in
  `/admin/clients` like any other, and can be edited or deleted there.
