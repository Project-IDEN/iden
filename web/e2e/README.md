# IDEN end-to-end tests (Playwright)

Browser tests of the dashboard and the hosted sign-in pages against the **local**
docker compose stack. Never point them at a deployment on the internet: setup
creates accounts and a client through the admin API, and teardown deletes every
account and client whose id starts with `e2e-`.

| What                     | Default                                        | Override             |
| ------------------------ | ---------------------------------------------- | -------------------- |
| Provider                 | `http://localhost:8000`                        | `E2E_ISSUER`         |
| Auth UI                  | `http://localhost:4000`                        | `E2E_AUTH_UI`        |
| Dashboard                | `http://localhost:3000` (app under `/console`) | `E2E_DASHBOARD`      |
| Administrator            | `admin@localhost`                              | `E2E_ADMIN_EMAIL`    |
| Administrator's password | — (required)                                   | `E2E_ADMIN_PASSWORD` |

The administrator must not have an authenticator enrolled: setup signs in as
them with a password alone to get an admin token.

## Run

```bash
# 1. The stack, from the repository root
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec \
  -e IDEN_BOOTSTRAP_ADMIN_PASSWORD='choose-one-12+' provider python -m scripts.seed

# 2. Dependencies and the browser, from web/
pnpm install
pnpm --filter @iden/e2e exec playwright install chromium

# 3. The suite, from web/
E2E_ADMIN_PASSWORD='choose-one-12+' pnpm e2e
#   PowerShell: $env:E2E_ADMIN_PASSWORD='choose-one-12+'; pnpm e2e
```

Results go to the repository's `test-results/`: `e2e.xml` (JUnit), `e2e-report/`
(HTML, `pnpm --filter @iden/e2e exec playwright show-report ../../test-results/e2e-report`)
and `e2e-artifacts/` (traces and screenshots of failures).

The tests run one at a time: they all sign in through the same provider, and its
per-address sign-in limit (30 attempts per five minutes) is shared by the run.
A full run signs in about fifteen times.

## What is covered

| Id  | File                     | Behaviour                                                                 |
| --- | ------------------------ | ------------------------------------------------------------------------- |
| D1  | `tests/sign-in.spec.ts`  | Password sign-in lands on the dashboard showing the person's name         |
| D2  | `tests/sign-in.spec.ts`  | A wrong password shows a notice and stays on the sign-in page             |
| D3  | `tests/totp.spec.ts`     | Enrol TOTP on Security, sign out, sign in with password + TOTP (`otplib`) |
| D4  | `tests/consent.spec.ts`  | Third-party client: approve → back with a code; deny → `access_denied`    |
| D5  | `tests/access.spec.ts`   | A member has no admin navigation, and admin URLs are blocked              |
| D6  | `tests/admin.spec.ts`    | Admin creates a user; the generated password is shown once                |
| D7  | `tests/admin.spec.ts`    | Admin registers a confidential client; the secret is shown once           |
| D8  | `tests/sessions.spec.ts` | Revoking another session ends it (`login_required` on its next request)   |
| D9  | `tests/recovery.spec.ts` | Forgot password answers known and unknown addresses identically           |
| D10 | `tests/sign-in.spec.ts`  | Sign-out clears the session; a protected page goes back to sign-in        |
