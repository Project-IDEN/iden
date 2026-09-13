# May you?

The other three samples answer *who are you*. This one answers the question that
comes after it, and it is a different question with a different owner.

Two processes. A **panel** on :5401 that signs you in and draws three doors, and
a **door controller** on :5400 that decides whether any of them open. The panel
has no opinion — press any door and find out. Every decision is made by the
controller, from an access token, offline, with no call back to IDEN and no
database between the two.

```
  Panel :5401  ───Bearer token───►  Controller :5400
       │                                    │
       └──► IDEN                            │
            issues the token                │
            ◄───public keys, fetched once ──┘
```

That split is the whole point, and it is worth saying why rather than only
showing it. A panel that decided for itself would be deciding from data it was
handed, and whoever holds the browser can change that. A door opens because a
separate process read a signed token and did arithmetic on it.

## What it demonstrates

- **A scope check that is not an authentication check.** The lab returns `403`
  with the missing permission named. Signing in again produces exactly the same
  token; only an administrator can change the answer.
- **The audience check people skip.** The controller refuses any token not
  addressed to it, even one IDEN signed a moment ago for something else.
  Verifying the signature proves IDEN wrote the token, not that IDEN wrote it
  *for this door*.
- **Silent pruning.** The panel asks for all three door scopes on every sign-in,
  whoever is signing in. What comes back is the intersection of what was asked,
  what the client may ask, and what the person holds — narrowed without an
  error, because failing the sign-in would lock out everyone who lacks one
  optional permission.
- **Permissions change at the next token, and the two directions differ.**
  A revoked role disappears on the next *refresh*. A newly granted one cannot
  arrive that way at all — a refresh may only narrow the grant it came from — so
  it takes a new authorization request. The asymmetry is deliberate and it
  surprises everybody once.
- **Step-up, and a refusal that tells you how to succeed.** The server room
  wants two factors within the last five minutes and says so in
  `WWW-Authenticate`. The panel copies those parameters onto the next
  authorization request; IDEN walks you through the missing step.
- **Where a permission came from.** A token carries `scope` and nothing else —
  no roles, no groups. `GET /entity/permissions` answers that separately, for
  the person rather than for the resource server.

## The building

| Door | Needs | Also demands |
|---|---|---|
| Front door | `door:front:open` | — |
| Lab | `door:lab:open` | — |
| Server room | `door:server:open` | `acr` of `iden:loa:2`, and a sign-in within 300s |

The doors on the page are drawn rather than described, and they move: one
swings open, one rattles in its frame without budging, and the server room
cracks open and shuts again — permission held, assurance missing. It is all
CSS. The panel ships no client JavaScript, and an animation starts because the
server rendered a different class than it did last time.

One scope per door rather than one `door:open` for all three, because IDEN has
no resource-instance permissions — there is no way to say *may open door 7 but
not door 12*. A door that needs its own answer needs its own scope. That is
fine for a building and wrong for ten thousand documents; the rough line is
whether a person could name them all.

---

# Setting it up

Nothing here is created for you. This sample needs more objects than the other
three — a resource API, three scopes, three roles, a group, a client and a user
— so work through this once, in order. Later steps refer to earlier ones by id.

Everything below can be done from the dashboard, and each step also shows the
admin API call underneath it. `$ADMIN_TOKEN` is an access token carrying the
`admin:*` scopes; the quickest way to get one is to sign in to the dashboard as
an administrator and copy the bearer token from any `/admin/` request in your
browser's developer tools. `$IDEN` is your deployment's base URL.

## 1. Register the resource API

The API is the thing that owns the permissions, and its **audience** is what
every token for those permissions will be addressed to. Pick a value and keep
it: the audience cannot be changed later, because every token already minted
carries the old one.

**Dashboard:** *APIs → Register API*

| Field | Value |
|---|---|
| Name | `door` |
| Audience | `https://api.example.org/door` |
| Description | The building's door controller. |

```bash
curl -X POST $IDEN/admin/apis \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "door", "audience": "https://api.example.org/door",
       "description": "The building'"'"'s door controller."}'
```

The audience is an identifier, not an address. Nothing dereferences it and IDEN
never calls it — it only has to be an absolute URI, and it has to match the
controller's `DOOR_AUDIENCE` character for character.

## 2. Define the three scopes

Under that API, one per door. Note the ids that come back.

**Dashboard:** open the `door` API → *Scopes → Define scope*, three times.

| Value | Description |
|---|---|
| `door:front:open` | Open the front door. |
| `door:lab:open` | Open the lab. |
| `door:server:open` | Open the server room. |

```bash
curl -X POST $IDEN/admin/apis/{api-id}/scopes \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"value": "door:lab:open", "description": "Open the lab."}'
```

`description` is required and it is not paperwork — it is the sentence somebody
reads on the consent screen. Reading *Open the lab.* next to a checkbox is the
clearest statement of what this sample is about, which is why the panel's client
is registered below with consent left **on**.

## 3. Create a role for each door

Three roles, one scope each, so granting one in the dashboard opens exactly one
door. That is what makes the third experiment below legible.

**Dashboard:** *Roles → Create role*, three times, attaching one scope to each.

| Role | Scope |
|---|---|
| `door-staff` | `door:front:open` |
| `door-technician` | `door:lab:open` |
| `door-engineer` | `door:server:open` |

```bash
curl -X POST $IDEN/admin/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "door-technician", "description": "Works in the lab.",
       "scopeIds": ["{door:lab:open scope id}"]}'
```

## 4. Create a group, and give it the front door

**Dashboard:** *Groups → Create group* → `Facilities`, then attach the
`door-staff` role to it.

```bash
curl -X POST $IDEN/admin/groups \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "Facilities", "description": "Keeps the building running."}'

curl -X PUT $IDEN/admin/groups/{group-id}/roles \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"roleIds": ["{door-staff role id}"]}'
```

A group rather than putting the role straight on the person, so the panel's
provenance view has something to say: it will report the front door as held
*via group Facilities*, which is how permissions actually reach people in an
organization of any size.

## 5. Register the panel's client

**Dashboard:** *Clients → Register client*

| Field | Value |
|---|---|
| Name | Door Panel |
| Client ID | `demo-door-panel` |
| Application type | Web application (confidential) |
| Redirect URI | `http://localhost:5401/api/callback` |

Then, on the client's detail page:

- **Post-logout redirect URI** — `http://localhost:5401/`
- **Allowed grants** — `authorization_code` *and* `refresh_token`
- **Grantable scopes** — all three `door:*` scopes, plus `entity:permissions:read`
- **Consent** — leave it on

```bash
curl -X POST $IDEN/admin/clients \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "clientId": "demo-door-panel",
    "name": "Door Panel",
    "clientType": "confidential",
    "allowedGrants": ["authorization_code", "refresh_token"],
    "redirectUris": ["http://localhost:5401/api/callback"],
    "postLogoutRedirectUris": ["http://localhost:5401/"],
    "skipConsent": false,
    "grantableScopeIds": ["{three door scope ids}", "{entity:permissions:read id}"]
  }'
```

**The `clientSecret` is in that response and IDEN will not show it again.** Put
it in `panel/.env.local` now. If you lose it, rotate it — the old one stops
working immediately.

Two of those settings exist only so the demo can work, and both are easy to miss:

- **`refresh_token` in allowed grants.** Without it the *Refresh this token*
  button has nothing to trade, and the revocation experiment below cannot be
  run. The grant is only half of it; the panel also requests the
  `offline_access` scope, and a refresh token needs both.
- **`entity:permissions:read` as grantable.** Without it the provenance card
  never appears, silently — the panel treats a refusal there as "not granted"
  rather than breaking the page.

Grantable is a ceiling, not a grant. Listing a scope here lets the client *ask*
for it; whether it arrives still depends on the person holding it.

## 6. Give somebody the front door and nothing else

Use your own account or make one. Either way it needs two things:

- the **`member`** role, which carries `entity:permissions:read`
- membership of **`Facilities`**

**Dashboard:** *Users → Create user*, then set roles and groups on their detail
page.

```bash
curl -X POST $IDEN/admin/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"email": "keeper@door.local", "username": "keeper",
       "displayName": "Dana Keeper", "password": "a-long-enough-password",
       "roleIds": ["{member role id}"], "groupIds": ["{Facilities group id}"]}'
```

A new user holds **no roles at all** — not even `member`. Miss that and the
provenance card comes back empty for reasons that look like a bug in the panel
rather than a missing role.

Leave them out of `door-technician` and `door-engineer` for now. Granting those
later, while the panel is open, is the demonstration.

## 7. To try the server room, enrol an authenticator

The server room wants `iden:loa:2`, which means two factors. Sign in as that
person, go to the dashboard's security settings, and set up an authenticator
app. Without it the step-up round trip has nothing to step up *to*: IDEN
answers *Prove it again* with `unmet_authentication_requirements`, and the
panel shows that instead of a sign-in page you could never get past.

## What you do not need

- **No CORS allowlist entry.** Both processes here are servers. The browser
  never talks to IDEN or to the controller directly, so
  `IDEN_ALLOWED_ADMIN_ORIGINS` is irrelevant to this sample.
- **No back-channel logout URI.** This sample does not demonstrate sign-out;
  `single-sign-out` does.

---

# Running it

Two terminals, or use the compose file in [`../docker-compose.yml`](../docker-compose.yml).

```bash
# The controller. It needs no secret — see api/.env.example for why that is
# the interesting part.
cd api
cp .env.example .env
pnpm install
pnpm dev

# The panel, in another terminal.
cd panel
cp .env.example .env.local     # put the client secret in it
pnpm install
pnpm dev
```

Then open <http://localhost:5401>.

| Variable | Where | Default |
|---|---|---|
| `IDEN_ISSUER` | both | `http://localhost:8000` |
| `DOOR_AUDIENCE` | api | `https://api.example.org/door` |
| `DOOR_PANEL_CLIENT_ID` | panel | `demo-door-panel` |
| `DOOR_PANEL_CLIENT_SECRET` | panel | — required |
| `DOOR_PANEL_ORIGIN` | panel | `http://localhost:5401` |
| `DOOR_API_ORIGIN` | panel | `http://localhost:5400` |

# Things worth trying

**Press all three doors straight after signing in.** The front door opens. The
lab returns `403 insufficient_scope` naming `door:lab:open`. Look at the
`scope` row on the token card: the panel asked for all three and was quietly
given one.

**Grant yourself the lab, then press it again.** In the dashboard, add
`door-technician` to your user. Press *Open* on the lab — it still refuses, with
the same message. Nothing has gone wrong: your access token was minted before
the grant existed and is self-contained by design.

Now press **Refresh this token**. The lab *still* refuses, and this is the part
worth slowing down for. A refresh re-resolves your permissions, but it may only
ever narrow the grant it was issued from — RFC 6749 Section 6 forbids returning
more than was granted originally, and an intersection cannot widen. Your
original grant did not include `door:lab:open`, so no rotation of it ever will.

Press **Sign in again**. You are not asked for a password — the IDEN session is
still there — but this is a fresh authorization request, evaluated against what
you hold *now*. The lab opens.

**Now take the role away again, and refresh.** This time the refresh is enough:
`door:lab:open` vanishes from `scope` and the lab closes. Revocation travels by
the cheap path, and acquisition does not. That is the right way round — the
expensive direction is the one that grants power.

Between those two, note that the *old* access token keeps working until it
expires, ten minutes by default. That is the cost of validating offline, and it
is the trade the controller is making on purpose.

**Press the server room.** `403 insufficient_user_authentication`, with a
`max_age` and an `acr_values` in the challenge rather than a dead end. Press
*Prove it again*, enter a code from your authenticator, and come back. The
`acr` row on the token card has changed from `iden:loa:1` to `iden:loa:2` and
the door opens.

**Then wait five minutes and press it again.** It refuses once more. The
permission never went anywhere — what expired was the *recency* of your
sign-in, which is a different question that the same door asks separately.

**Point the controller at the wrong audience.** Set `DOOR_AUDIENCE` to something
else and restart it. Every door now returns `401`, because a token addressed
elsewhere is not evidence about this service — even though IDEN signed it and
the scopes inside it look right.

# Troubleshooting

**`No bearer token.`** — the panel has no session, or its session lost its
access token. Sign in again.

**`401 unexpected "aud" claim value`** — the controller's `DOOR_AUDIENCE` and
the audience registered on the `door` API in IDEN do not match. They are
compared as strings.

**`403 insufficient_scope` on the front door** — the person is not in
`Facilities`, or the group has lost the `door-staff` role. The provenance card
tells you which.

**Every door refuses and `scope` is empty** — the client's grantable scopes are
not set. Holding a permission and being allowed to request it are separate
gates, and this is the second one.

**No provenance card** — the client cannot request `entity:permissions:read`, or
the person does not hold it. Both are needed; the `member` role carries it.

**`Refresh this token` does nothing** — if `scope` does not change at all, no
refresh token was issued: the client needs the `refresh_token` grant *and* the
request needs `offline_access`. The panel always asks for the scope, so it is
almost always the grant. If `scope` is unchanged because a newly granted role
did not appear, that is not a fault — use *Sign in again*.

**`The door controller is not answering`** — the panel reaches it at
`DOOR_API_ORIGIN`. Inside Docker that is the service name, `http://door-api:5400`,
not `localhost` — which in a container is the container.
