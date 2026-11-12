# Changelog

Notable changes to IDEN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-11-12

The release shown on demonstration day.

### Removed

- **Self-service password recovery**, and every email IDEN sent. There is no mail transport, so the
  "Forgot your password?" flow could never deliver. `POST /api/v1/auth/password-reset` and
  `/password-reset/confirm` are gone, along with the auth-ui pages. An administrator issues a new
  password from the dashboard; `scripts.change_pass` sets a lost bootstrap password.

### Security

- A session kept alive past a day is now ended by a password reset, a password change and "sign out
  everywhere"; before, it fell out of the index those use and survived for up to seven days.
- An administrator can no longer take away an `admin:` or `biometric:` scope they could not grant —
  by removing a member, deleting a group or role, or emptying a role.
- The engine refuses every caller in prod if its token file reads empty, rather than turning
  authentication off.
- The engine rejects an oversized JPEG from its header, before decoding it, and caps how many
  captures it computes at once (`ENGINE_MAX_INFLIGHT`, `ENGINE_QUEUE_SECONDS`).
- A standalone engine listens on loopback unless `ENGINE_PUBLISH` names an address.
- The kiosk refuses a plain-http issuer across the internet in prod, and its Chromium is locked to
  the kiosk app.
- Dependencies with published advisories were upgraded: pyjwt 2.15, Pillow 13, and others.
- Every base and service image is pinned to an exact version.
- A logout link that does not carry the signed-in person's `id_token_hint` asks before signing
  out, so a cross-site page can no longer end someone's session with a `GET`. Applications that send
  the hint, the dashboard included, sign out as before.
- Reusing an authorization code revokes the refresh tokens it already issued.
- Token introspection reports a deactivated person's token as inactive.
- A face ticket's five attempts hold even when captures arrive at once.
- Uploads are decoded only as JPEG, PNG, WebP or GIF.
- What a caller sends (an unknown key ID, say) no longer reaches the `WWW-Authenticate` header.
- The login form caps email and password length, the code that confirms an authenticator cannot
  also sign in, and a challenge ID is redacted from the audit log.
- Profile fields may not claim `events`, `at_hash`, `c_hash`, `cnf` or `updated_at`.
- In prod the provider refuses a store password or S3 secret key shorter than 16 characters; Redis's
  healthcheck keeps its password out of the process list; nginx no longer sends its version.
- The tunnel overlay refuses to start without `IDEN_FORWARDED_ALLOW_IPS`.

### Fixed

- A plain `uv sync` in `engine/` installs onnxruntime. It was an optional extra, so the sync
  removed it; it is now a default dependency group (`cpu`), and an NVIDIA host syncs with
  `--no-group cpu --group gpu`.
- The dashboard sends a person to sign in when the provider stops accepting its token, instead of
  an error that could never be retried.
- A kiosk update that does not come up goes back to the previous image (`iden-kiosk rollback` does
  it by hand), its credentials survive a power cut, and its maintenance screens close themselves.
- Web image builds no longer pick up a developer's `node_modules` or `.env`.
- Deactivating or deleting the last administrator is refused before any session is ended or any
  application notified, not after.
- A refresh token that is already being exchanged answers `503 temporarily_unavailable`, not a 500.
- The engine answers a face template of the wrong length with a 400, not a 500.
- The lowercase-email migration names the accounts that differ only by capitalisation, instead of
  stopping halfway on an unnamed integrity error.
- A newline in an operator's setting no longer breaks the frontends' `config.js`.
- An unplugged kiosk camera says so and is reported to IDEN; the heartbeat interval has a 5-second
  floor; the installer warns when it cannot turn off screen blanking.
- The dashboard starts one sign-in redirect, not two, under React's StrictMode.
- The provider's test suite makes throwaway signing keys on a fresh clone.

### Added

- CI for the provider, engine and kiosk, a weekly dependency audit, and Dependabot.
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `NOTICE`, and issue and pull request
  templates.
- A Known Limitations section in the README.
