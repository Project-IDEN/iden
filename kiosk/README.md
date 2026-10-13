# IDEN kiosk

The device where people enrol their face: a Raspberry Pi with a touchscreen and a USB webcam.

| | |
|---|---|
| `server/` | The kiosk server. Holds the kiosk's client secret, pairs with IDEN, reports in every minute, and relays captures. Serves the kiosk app on `localhost:8080`. |
| `../web/kiosk/` | The kiosk app: QR scanning, the face capture, the screens a person sees. |
| `Dockerfile` | Both in one image, for arm64 and amd64. Built from the repository root. |
| `deploy/` | What turns a Raspberry Pi into a kiosk: `install.sh`, Chromium in kiosk mode, camera and screen settings, nightly updates. |

Installing, pairing and tuning one: [doc/operations/kiosks.md](../doc/operations/kiosks.md).

The server's checks, from `server/`:

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```
