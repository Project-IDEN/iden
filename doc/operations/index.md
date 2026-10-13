# Operations

Running IDEN somewhere real.

- **[Deployment](deployment.md)** — what to run, in what order, and how to upgrade it.
- **[Behind a Cloudflare Tunnel](cloudflare-tunnel.md)**: the full install, from a clone to a
  signed-in administrator, with nginx in front, no inbound port, and one origin.
- **[Backup and restore](backup-and-restore.md)** — what to keep, how to put it back, and how to
  prove the backup works before you need it.
- **[The biometric engine](biometric-engine.md)** — turning faces on, running the engine on a GPU,
  and calibrating it on your own cameras.
- **[Kiosks](kiosks.md)** — the devices where faces are enrolled: building the image, installing one
  on a Raspberry Pi, pairing it, running it with `iden-kiosk`, and revoking it.
- **[Tuning the kiosk camera](kiosk-camera.md)** — setting any webcam up for the kiosk's light, so
  enrolment works first time.
- **[Before you expose it](security-checklist.md)** — what must be true before anyone outside your
  machine can reach it.

!!! warning "Not production-ready yet"
    IDEN is in active development. The checklist is honest about what is missing rather than
    reassuring, and there are unresolved issues on the [roadmap](../roadmap.md).
