# Backup and restore

Losing an identity provider's database locks every person in your organization out of every
application that trusts it. This page is the procedure, and the last section is the one that
matters — a backup nobody has restored is a hope, not a backup.

Every command here has been run end to end: dump, destroy the volumes, restore, sign in.

## What to back up

| | Back it up? | If you lose it |
|---|---|---|
| **PostgreSQL** | **Yes.** This is the deployment. | People, permissions, clients, roles, and the audit log are gone. Unrecoverable. |
| **Signing keys** (`provider/keys/*.pem`) | **Yes**, separately, with different access. | Every token in circulation becomes unverifiable. Recoverable — generate a new key and everyone signs in again — but noisy. |
| **Secret key** (`provider/keys/totp.key`) | **Yes**, with the signing keys. | Every enrolled authenticator stops verifying, and those people cannot sign in: they owe a second factor nobody can check. Recovering means an administrator clearing each enrolment so they can set one up again. |
| **Object store** (profile photos) | Optional. | Photos 404 and people re-upload them. `pictureUrl` still points at the missing object, so the row is stale rather than broken. |
| **Redis** | **No.** | Everyone signs in again. Nothing permanent is lost — it holds sessions, pending sign-ins, the denylist and rate-limit counters. |

Keep the database and the keys in **different places with different access**. Together they are the
whole system; whoever holds both can mint a token for anyone.

## Backing up

### PostgreSQL

```bash
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U iden -d iden -Fc > iden-$(date +%F).dump
```

`-Fc` is PostgreSQL's custom format: compressed, and restorable selectively. A seeded deployment
with no people in it is about 44 KB, so this stays small for a long time.

**Check the dump is readable** rather than trusting that it was written:

```bash
docker compose -f deploy/docker-compose.yml exec -T -i postgres \
  pg_restore -l < iden-2026-09-10.dump | head
```

That lists what the archive contains without touching anything. A truncated or half-written dump
fails here, which is where you want to find out.

### Signing keys

```bash
tar czf iden-keys-$(date +%F).tar.gz -C provider keys
```

That takes the whole directory, which is deliberate: it holds the signing keys *and* `totp.key`,
and the second one is the easier to forget and the more painful to lose. A missing signing key
signs everyone out; a missing `totp.key` leaves everyone with MFA unable to sign in at all.

Then put it somewhere you would be comfortable keeping a password — not beside the database dump.

### Scheduling it

A cron entry, a systemd timer, or whatever your organization already runs:

```bash
#!/bin/sh
# Nightly. Keeps 30 days.
set -e
cd /srv/iden
out=/backup/iden
mkdir -p "$out"

docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U iden -d iden -Fc > "$out/iden-$(date +%F).dump"

find "$out" -name 'iden-*.dump' -mtime +30 -delete
```

`set -e` matters: without it, a failed dump leaves yesterday's file in place and the job reports
success.

## Restoring

Order matters, and the provider must not be talking to the database while it is replaced.

```bash
# 1. Stop the application. Leave PostgreSQL running — it is the thing being restored into.
docker compose -f deploy/docker-compose.yml stop provider

# 2. Restore. --clean drops what is there first; --if-exists stops that failing on an empty
#    database, so the same command works whether you are recovering in place or into a fresh host.
docker compose -f deploy/docker-compose.yml exec -T -i postgres \
  pg_restore -U iden -d iden --clean --if-exists --no-owner < iden-2026-09-10.dump

# 3. Bring the schema up to the running code. The dump carries the alembic_version it was taken
#    at, so restoring an older backup moves the schema *backwards*. Skip this and the provider
#    starts against a schema it does not expect.
docker compose -f deploy/docker-compose.yml run --rm migrate

# 4. Start it again.
docker compose -f deploy/docker-compose.yml start provider
```

If the signing keys were lost too, restore them into `provider/keys/` before step 4 — or
[generate a new one](../guides/install.md#2-generate-a-signing-key) and accept that everyone signs
in again.

### What comes back, and what does not

| | After a restore |
|---|---|
| People, roles, groups, clients, scopes | Exactly as they were at the dump |
| The audit log | Exactly as it was. Entries since the dump are gone. |
| Refresh tokens | Valid, if the signing keys are the same ones |
| **Browser sessions** | **Gone.** They live in Redis, which is not backed up — everyone signs in again. |
| Profile photos | Only if the object store was restored too; otherwise the URLs 404 |

Expect a wave of sign-ins after any restore. That is the design working, not a fault.

## Testing it

!!! danger "An untested backup is a hope"
    This is the step the [security checklist](security-checklist.md) requires, and the one that
    gets skipped. Do it once now, and once a year after that.

Never test by restoring over production. Use a throwaway Compose project — `-p` gives it its own
volumes, so nothing you already run is touched:

```bash
# A separate deployment, from the same files.
docker compose -p iden-restore-test -f deploy/docker-compose.yml up -d
sleep 15

docker compose -p iden-restore-test -f deploy/docker-compose.yml exec -T -i postgres \
  pg_restore -U iden -d iden --clean --if-exists --no-owner < iden-2026-09-10.dump

docker compose -p iden-restore-test -f deploy/docker-compose.yml run --rm migrate
docker compose -p iden-restore-test -f deploy/docker-compose.yml restart provider
```

Then prove it, rather than looking at row counts:

```bash
# The catalogue survived
docker compose -p iden-restore-test -f deploy/docker-compose.yml exec -T postgres \
  psql -U iden -d iden -t -c \
  "select (select count(*) from users), (select count(*) from scopes), (select count(*) from clients);"

# The provider serves against it
curl -s http://localhost:8000/health
```

**And sign in.** Open <http://localhost:3000/console/> and authenticate as a real administrator. A
restore that produces the right row counts but cannot authenticate anyone has not been tested — the
password hashes, the role grants and the client records all have to be right together, and only a
sign-in exercises all three.

Tear it down when you are satisfied:

```bash
docker compose -p iden-restore-test -f deploy/docker-compose.yml down -v
```

The `-v` removes that project's volumes. It cannot touch the volumes of your real deployment, which
belong to a different project name.
