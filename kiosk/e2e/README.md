# Kiosk end-to-end tests (sheet M07)

Playwright drives the **real kiosk client UI** served by the **real kiosk server**
on `127.0.0.1:8080`, paired to the **local** provider on `localhost:8000`. Chromium
gets a fake camera that plays a `.y4m` file, so each case decides what the camera
sees: a blank frame, an enrolment QR code, or a badly lit face. Local only — never
point it at a deployment on the internet.

## What it needs running

```bash
# From the repository root: the stores, the provider with the biometric module,
# and the engine (GPU overlay; use docker-compose.engine-cpu.yml without a GPU).
IDEN_BIOMETRIC_ENABLED=true docker compose -f deploy/docker-compose.yml \
  -f deploy/docker-compose.engine-gpu.yml up -d postgres redis seaweedfs migrate provider engine

# The kiosk client, built once (fetches the MediaPipe head tracker into dist/)
cd kiosk/client && pnpm install && pnpm build && cd ../..

# This project, and its browser
cd kiosk/e2e && pnpm install && npx playwright install chromium
```

`uv` must be on the PATH: the suite starts the kiosk server with
`uv run --project kiosk/server` (see `scripts/start-kiosk.mjs`). Nothing else needs
to be running on port 8080.

## Run

```bash
cd kiosk/e2e
M07_ADMIN_EMAIL=tds-admin@localhost M07_ADMIN_PASSWORD='…' npx playwright test
node scripts/summary.mjs          # writes test-results-m07/SUMMARY.md
#   PowerShell: $env:M07_ADMIN_EMAIL='…'; $env:M07_ADMIN_PASSWORD='…'; npx playwright test
```

| Variable | Default | |
|---|---|---|
| `M07_ADMIN_EMAIL` | `admin@localhost` | An administrator without an authenticator: setup signs in with a password alone. |
| `M07_ADMIN_PASSWORD` | — (required) | |
| `M07_ISSUER` | `http://localhost:8000` | The provider, for the API and for the kiosk server's `KIOSK_ISSUER`. |
| `M07_REDIS_PASSWORD` | `iden` | For TC-204, which shortens a ticket's TTL with `redis-cli EXPIRE`. |
| `M07_CALLBACK` | `http://localhost:3000/console/callback` | The dashboard callback the sign-ins use (registered by `scripts.seed` in dev). |

## What a run does

- **Global setup** creates, through the admin API, a dedicated test user
  `m07-kiosk-<run>@<mail domain>` with the `member` role (never your account) and a kiosk
  registration `M07 Test Kiosk <run>`. It generates the camera files with ffmpeg
  (`ffmpeg-static`): `blank.y4m`, and `face-dark-15.png` — `engine/tests/data/astronaut.jpg`
  at 15 % brightness. Each 30 s file loops.
- **The kiosk server** starts unpaired (`node scripts/start-kiosk.mjs --fresh`), with its
  pairing kept in `kiosk/e2e/.kiosk-data/` rather than `kiosk/server/data/`.
- **Tickets** are created during the case that uses them, for the test user, with a token
  from the normal sign-in API (so its `auth_time` satisfies the five-minute fresh-sign-in
  rule). The QR code encodes the raw ticket string, which is what the dashboard's Security
  page draws (`QRCodeSVG value={ticket.ticket}`) and what the kiosk's scanner reads.
- **Global teardown** puts the kiosk back in service, checks the test user's face status
  (removing a face if one exists, which should never happen), deletes the test user, and
  writes `test-results-m07/teardown.json`. **The kiosk stays registered and paired.**

## After the run: the kiosk for the hand-run cases

The kiosk server stops with the run, but its pairing stays in `.kiosk-data/`. To use the
same paired kiosk for TC-206/207/208:

```bash
cd kiosk/e2e && node scripts/start-kiosk.mjs      # no --fresh: keeps the pairing
# then open http://127.0.0.1:8080 in Chromium (with a real camera)
```

## Cases

All in `tests/m07.spec.ts`, in this order (TC-197 pairs the kiosk the rest use):

| TC | Case |
|---|---|
| TC-198 | `ABCD-EFGH` on the Setup keypad is refused and Setup stays |
| TC-197 | The real pairing code pairs the kiosk; the admin API shows it online |
| TC-201 | Holding the top-left corner for 5 s opens Maintenance; closed without re-pairing |
| TC-199 | `inService=false` + notice → Out of service with the notice; `inService=true` → idle |
| TC-200 | `docker compose stop provider` → "cannot reach IDEN"; `start provider` → idle |
| TC-202 | Declining consent returns to idle with zero `getUserMedia` calls |
| TC-203 | A fresh ticket's QR shows the test user's display name on the confirm screen |
| TC-205 | "No, that's not me" returns to idle; the test user has no face |
| TC-204 | A ticket whose Redis key was expired is refused ("This code can't be used") |
| TC-209 | A face at 15 % brightness through the capture, with the real head tracker |
| TC-209 (timed-capture path) | The same with the head tracker blocked, so the frames reach the engine |
| TC-210 | Left on the confirm screen, the kiosk returns to idle after `idleSeconds` |

Every case screenshots its expected-result moment to
`test-results-m07/screenshots/<TC id>.png`. Results: `test-results-m07/m07.xml` (JUnit),
`report/` (HTML), `results.json`, and `SUMMARY.md` from `scripts/summary.mjs`.
