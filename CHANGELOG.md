# Changelog

Notable changes to IDEN. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased — prepared for demonstration day

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

### Fixed

- The dashboard sends a person to sign in when the provider stops accepting its token, instead of
  an error that could never be retried.
- A kiosk update that does not come up goes back to the previous image (`iden-kiosk rollback` does
  it by hand), its credentials survive a power cut, and its maintenance screens close themselves.
- Web image builds no longer pick up a developer's `node_modules` or `.env`.

### Added

- CI for the provider, engine and kiosk, a weekly dependency audit, and Dependabot.
- `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `NOTICE`, and issue and pull request
  templates.
- A Known Limitations section in the README.
