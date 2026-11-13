# Guides

Task-shaped instructions. Each assumes you have read the [concepts](../concepts/index.md) it depends
on, and links back where it matters.

## Getting IDEN running

Four paths. Each is one page with every step, from an empty directory to a signed-in administrator.
[Install IDEN](install.md) compares them.

- **[On a laptop, in Docker](local-docker.md)**: the whole system in containers on `localhost`,
  to try or demo it. About fifteen minutes.
- **[Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md)**: the whole system on the
  internet for your organization, with no inbound port. About an hour.
- **[Run the provider from source](quickstart.md)**: the server alone, for reading the code,
  running the tests, or pointing an integration at it. About five minutes.
- **[Develop the frontends](run-the-frontends.md)**: the provider and both frontends from source,
  for working on the sign-in page and the dashboard.

Then **[After installing](first-steps.md)** checks every part and sets up your organization.

## Integrating an application

Start here if you are connecting something you built to IDEN.

1. **[Register your application](register-a-client.md)** — getting a `client_id`, and the choices
   that are hard to change later.
2. **[Using a standard OIDC library](oidc-libraries.md)** — the configuration for browser apps,
   server-rendered apps, mobile, and backends. Do not hand-roll the protocol.
3. **[Add a web application](web-application.md)** — the flow itself, step by step, if you want to
   see what the library is doing.
4. **[Add a machine client](machine-client.md)** — a backend acting as itself, no person involved.
5. **[Validate tokens in your API](protect-an-api.md)** — the other side, in any language.
6. **[Handle single sign-out](single-sign-out.md)** — so that signing out means something.
7. **[Troubleshooting](troubleshooting.md)** — symptom first, then what IDEN is telling you.

## Administering IDEN

- **[Define your profile schema](profile-schema.md)** — the fields your organization collects about
  people, beyond name and email.

Then [Before you expose it](../operations/security-checklist.md), which is the list to work through
before anyone outside your own machine can reach the deployment.

## Calling the admin API yourself

Everything the guides do with `curl` can also be done in the dashboard, under **Administration**.
The `curl` examples are for scripting it, and for seeing exactly what is sent.

They authenticate with `$ADMIN_TOKEN`: an access token for someone who holds the permissions the
call needs — usually you, as an administrator. The quickest way to get one is from a dashboard tab
you are signed in to. Open the browser's developer tools, go to the **Console**, and run:

```js
JSON.parse(sessionStorage.getItem(Object.keys(sessionStorage).find((k) => k.startsWith("oidc.user:")))).access_token
```

Copy the result, then in your terminal:

```bash
export ADMIN_TOKEN='eyJ...'
```

It carries every admin permission you hold, and lasts at most ten minutes; copy a fresh one when
calls start answering `401`. Keep it out of anything that is saved or shared — for those ten minutes it
can do whatever you can.

For a script that runs unattended, register a [machine client](machine-client.md) holding only the
permissions that script needs, rather than borrowing a person's token.

### Where the ids in the examples come from

Paths such as `/admin/clients/{id}` and fields such as `grantableScopeIds` take an **`id`**: a UUID
that IDEN generated when the thing was created, like `0b9e4c2a-…`. It is returned as `"id"` in the
response to the call that created it, and shown in the dashboard. It is never a name you chose:
for a client, `{id}` is **not** its `clientId` (`library`).

To look one up, list the things of that kind and pick out the `id`. These use
[`jq`](https://jqlang.org/); without it, read the `"id"` from the JSON by eye:

```bash
# A client's id, from its clientId
curl -s http://localhost:8000/admin/clients -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.items[] | select(.clientId == "library") | .id'

# An API's id, from its name
curl -s http://localhost:8000/admin/apis -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.items[] | select(.name == "attendance") | .id'

# The ids of that API's scopes, with their values
curl -s http://localhost:8000/admin/apis/$API_ID/scopes -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.items[] | "\(.id)  \(.value)"'

# A role's id, from its name
curl -s http://localhost:8000/admin/roles -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.items[] | select(.name == "developer") | .id'

# A person's id, from part of their email
curl -s "http://localhost:8000/admin/users?search=sarah" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq -r '.items[] | "\(.id)  \(.email)"'
```

Save the one you need in a shell variable, such as `export CLIENT_ID_UUID=0b9e4c2a-…`, and the
examples that use `$CLIENT_ID_UUID` work as written. Replace `localhost:8000` with your issuer
when you are not on a laptop install.
