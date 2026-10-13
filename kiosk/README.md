# IDEN kiosk

The device where people enrol their face: a Raspberry Pi with a touchscreen and a USB webcam.

| | |
|---|---|
| `server/` | The kiosk server. Holds the kiosk's client secret, pairs with IDEN, reports in every minute, and relays captures. Serves the kiosk app on `localhost:8080`. |
| `client/` | The kiosk app: QR scanning, the face capture, the screens a person sees. Its own pnpm project. |
| `Dockerfile` | Both in one image, for arm64 and amd64. `kiosk/` is the build context; nothing outside it is used. |
| `build.sh` | Builds the image for both platforms and pushes it, setting up buildx and QEMU on Linux first. `--local` builds for this machine only. |
| `deploy/` | What turns a Raspberry Pi into a kiosk: `install.sh`, the `iden-kiosk` command, the browser, camera and screen settings, nightly updates. |

- Installing and running one: [doc/operations/kiosks.md](../doc/operations/kiosks.md)
- Tuning its camera: [doc/operations/kiosk-camera.md](../doc/operations/kiosk-camera.md)

Checks — the server's from `server/`, the client's from `client/`, the scripts' from `kiosk/`:

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
pnpm install && pnpm typecheck && pnpm lint && pnpm build
docker run --rm -v "$PWD:/mnt" koalaman/shellcheck:v0.10.0 build.sh deploy/*.sh deploy/iden-kiosk
```
