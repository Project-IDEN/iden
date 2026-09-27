# After installing

You have a running deployment and a signed-in administrator. This page checks that every part of it
works, then sets up your organization in an order that avoids rework. It is the same however you
installed. Only the address you open differs:

| Installed | Dashboard |
|---|---|
| [On a laptop, in Docker](local-docker.md) | <http://localhost:3000/console/> |
| [Behind a Cloudflare Tunnel](../operations/cloudflare-tunnel.md) | `https://iden.example.org/console/` |
| [Develop the frontends](run-the-frontends.md) | <http://localhost:5173/console/> |

## Check every part works

This takes about fifteen minutes, all of it in the two browser apps. Each row tests a different part
of the system, and the order matters because later rows depend on earlier ones.

### Signing in

| Do this | You should see |
|---|---|
| Open the dashboard signed out | The sign-in page, naming the application that's asking |
| Sign in with the bootstrap password | The dashboard, with an **Administration** section in the sidebar |
| **Security** → change the bootstrap password | A prompt for your current password, then a note on how many other sessions were signed out |
| **Security** → set up an authenticator, scan the QR code, confirm | Two-factor on |
| Sign out, then sign in again | A code step after the password |
| **Sessions** | This browser listed as current, with `Password + Authenticator app` |

Once an authenticator is enrolled, IDEN asks for the code on **every** sign-in, whatever the
application requested. See [Assurance](../concepts/assurance.md).

### Self-service

| Do this | You should see |
|---|---|
| **Profile** → change your display name → Save changes | "Saved." |
| **Permissions** | Every permission you hold, and where each one comes from |

The **Permissions** screen answers *why can this person do that?* Administrators get the same view
for anyone else.

### Administration

| Do this | You should see |
|---|---|
| **APIs** → Register API, then define a scope on it | The scope listed under its API |
| **Roles** → Create role → tick that scope → Save | The role holding the scope |
| **Users** → Add user → assign the role | An address on your mail domain, and a one-time password shown once |
| Open that user → **Everything they can do** | The new scope, traced back to the role |
| **Groups** → Create group → give it a role → add the user | The member count going up |
| Re-open the user | The group's role now among their permissions |
| **Clients** → Register client | A secret for a confidential client, nothing for a public one |
| **Audit log** | Every action above, newest first, with your name on each |

### The parts that are supposed to refuse

| Do this | You should see |
|---|---|
| Sign in as the new user, who holds only the `member` role | No **Administration** section |
| As that user, open `/console/admin/users` directly | An explanation, not a broken page |
| As an administrator, open **Roles** → `administrator` | Marked built-in and not editable |
| Try to delete an API whose scopes are in use | A refusal naming what still depends on it |
| Try to remove the `administrator` role from your own account | A `409` refusal, because you're the last administrator |
| Enter a wrong password five times quickly | A countdown, not a generic error |

People tend to skip the last three, but these refusals are what keep the deployment safe, so check
them too.

## Set up your organization

Work in this order, so you don't have to redo anything:

1. **[Profile fields](profile-schema.md).** Decide what you record about people beyond name and
   email. Everyone's profile form is built from this, so define it before you add anyone.
2. **[APIs and scopes](protect-an-api.md).** Register each backend that will trust IDEN, and define
   the permissions it understands.
3. **Roles.** Bundle those permissions into job functions. Name each role after the job, not after
   the permissions it happens to contain.
4. **Groups.** Create your departments and teams, and give them roles. Membership does the rest.
5. **People.** Add them and put them in groups. Save direct grants for real exceptions.
6. **[Your applications](register-a-client.md).** Register each one and choose what it may request.
   To let teams register their own, give them the `developer` role. See
   [Let people register their own](self-service-registration.md).

## Before you let anyone else in

Work through [Before you expose it](../operations/security-checklist.md) in full, then take a backup
and [restore it once](../operations/backup-and-restore.md#testing-it). A backup that has never been
restored isn't one you can count on yet.
