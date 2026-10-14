# The biometric engine

The engine is the one service that ever sees a face. It runs beside the provider, is reachable only
from it, keeps nothing between requests, and does the face work: finding the face, judging the
picture, checking it is live, and comparing it. What a face is for, and what is stored, is in
[Faces](../concepts/biometrics.md).

It is optional. Without it, and with `IDEN_BIOMETRIC_ENABLED=false`, IDEN is complete.

## Choose where it runs

The engine runs either **on the provider's host**, joining the same Docker network, or **on another
machine** — typically one with a GPU — that the provider reaches over your network. On either, it
runs on the CPU or on an NVIDIA GPU. That is four Compose files; you use exactly one:

| | CPU | NVIDIA GPU |
|---|---|---|
| **On the provider's host** | `deploy/docker-compose.engine-cpu.yml` | `deploy/docker-compose.engine-gpu.yml` |
| **On another machine** | `engine/deploy/compose.cpu.yml` | `engine/deploy/compose.gpu.yml` |

The CPU is enough to try it and for light use: a capture takes a few seconds. A GPU checks one in a
fraction of a second — see [On an NVIDIA GPU](#on-an-nvidia-gpu) for what the host needs.

Every step below needs only Docker on the machine it runs on.

## On the provider's host

Every command runs **on the provider's host, from the repository root**, the same place you run the
rest of the deployment.

**1. Name your Compose files once.** The deployment is now three files — the base, the tunnel if you
use one, and the engine — so set them in your shell rather than typing three `-f` flags each time:

```bash
export COMPOSE_FILE=deploy/docker-compose.yml:deploy/docker-compose.tunnel.yml:deploy/docker-compose.engine-cpu.yml
```

Leave out `deploy/docker-compose.tunnel.yml` if you do not use the tunnel; use
`docker-compose.engine-gpu.yml` on a GPU. Every `docker compose` command below then uses these
files. Add the line to your shell profile, so the engine stays part of every `up` — left out,
Compose leaves it running but no longer manages it.

**2. Generate the engine token**, the secret the provider presents to the engine. The command that
made your signing key writes it; on a deployment from before the engine existed, run it again. It
only writes files that are missing:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/provider/keys:/keys" -e IDEN_SIGNING_KEY_DIR=/keys \
  --entrypoint python iden-dev-provider:latest -m scripts.gen_keys
```

`ls provider/keys/` now shows `engine.token` beside the `.pem` and `totp.key`.

**3. Fetch the models** into `engine/models`. Build the engine's image, then run the download inside
it — about 290 MB, each file checked against the checksum in `engine/models.toml`:

```bash
docker compose build engine
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/engine/models:/app/models" \
  --entrypoint python iden-dev-engine:latest -m scripts.fetch_models
```

The download needs no GPU, and runs the same with either engine file. `--entrypoint python` skips
the GPU image's NVIDIA start-up banner, which would otherwise warn that no driver was detected — true
of this one-off container, and not of the engine, which Compose starts with the GPU.

Read the [model licences](../concepts/biometrics.md#the-models) before you go further: the default
models are for non-commercial research only.

**4. Turn the module on** in `deploy/.env`:

```bash
IDEN_BIOMETRIC_ENABLED=true
```

**5. Start it**, and add the face and kiosk permissions:

```bash
docker compose up -d --build
docker compose exec provider python -m scripts.seed
```

**Check it worked.** The engine logs which device it chose once its models are loaded:

```bash
docker compose logs engine | grep "Engine ready"
```

```text
engine-1  | {"event": "Engine ready", "model_version": "buffalo_l-liveness-1", "device": "cpu", "calibrated": false, ...}
```

And the provider can reach it:

```bash
docker compose exec provider python -c \
  "import urllib.request; print(urllib.request.urlopen('http://engine:8000/health/ready').read())"
```

```text
b'{"status":"ready"}'
```

**6. Sign out of the dashboard and back in.** The face section appears under **Security** once your
token carries `entity:face:read`, and **Kiosks** under Administration once it carries
`admin:kiosks:read`.

**7. Set up a kiosk** — see [Kiosks](kiosks.md).

The engine publishes no port. The provider reaches it at `http://engine:8000`, the default for
`IDEN_ENGINE_BASE_URL`. `IDEN_ENGINE_WORKERS` in `deploy/.env` sets how many captures it checks at
once.

## On another machine

The engine on a server of its own, while the provider and the web apps stay where they are. The
engine's folder holds everything it needs — its code, its `Dockerfile` and its Compose files in
`engine/deploy/` — so only `engine/` goes to that machine.

!!! warning "The link is not encrypted"
    The engine speaks plain HTTP, and what the provider sends it is faces and face templates. Run
    the two machines on a network you trust — a private LAN, or a VPN such as WireGuard or
    Tailscale between them — and let only the provider's machine reach the engine's port.

**On the engine's machine:**

1. **Get the engine's folder** there: a clone of the repository, or `scp -r engine` from one.

2. **Build the image and fetch the models**, from `engine/deploy/` (`compose.gpu.yml` on a GPU):

    ```bash
    cd engine/deploy
    docker compose -f compose.cpu.yml build
    docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/../models:/app/models" \
      --entrypoint python iden-engine-engine:latest -m scripts.fetch_models
    ```

3. **Copy the engine token** from the provider's host, so both sides hold the same one. From the
   provider's host:

    ```bash
    scp provider/keys/engine.token <engine-host>:engine/deploy/engine.token
    ```

4. **Choose where it listens.** `cp .env.example .env`, and set `ENGINE_PUBLISH` to the engine
   machine's private address and a port: `10.0.0.5:8000`. A port alone listens on every interface,
   and Docker's published ports bypass host firewalls such as `ufw`, so the address is what keeps
   it private.

5. **Start it:**

    ```bash
    docker compose -f compose.cpu.yml up -d
    docker compose -f compose.cpu.yml logs | grep "Engine ready"
    ```

**On the provider's host,** point the provider at it in `deploy/.env`, and turn the module on:

```bash
IDEN_BIOMETRIC_ENABLED=true
IDEN_ENGINE_BASE_URL=http://10.0.0.5:8000
```

Then, from the repository root, with your usual Compose files and **no** engine file among them
(leave out the tunnel file if you do not use one):

```bash
export COMPOSE_FILE=deploy/docker-compose.yml:deploy/docker-compose.tunnel.yml
docker compose up -d
docker compose exec provider python -m scripts.seed
```

Check the provider reaches the engine, at its address:

```bash
docker compose exec provider python -c \
  "import urllib.request; print(urllib.request.urlopen('http://10.0.0.5:8000/health/ready').read())"
```

Then steps 6 and 7 of the section above.

## On an NVIDIA GPU

The host needs:

- an NVIDIA GPU from **Pascal (GTX 10-series) on**;
- the NVIDIA driver, **575 or newer** — the image carries CUDA 12.9 and cuDNN 9;
- the NVIDIA Container Toolkit.

Check all three at once:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

It prints a table naming your GPU. Then use one of the two GPU files above. The engine reports
`"device": "cuda"` in its *Engine ready* line.

The GPU files set `ENGINE_DEVICE=cuda`, which makes the engine **refuse to start** when it cannot
see a GPU, instead of falling back to the CPU and serving twenty times slower without anyone
noticing.

Each worker (`IDEN_ENGINE_WORKERS`, or `ENGINE_WORKERS` on another machine) holds its own copy of the
models, up to about 1 GB of GPU memory, so size the number of workers to the card.

The image stays on CUDA 12 deliberately. CUDA 13 dropped Maxwell, Pascal and Volta, and onnxruntime
moved to it from 1.27, so the GPU build is held at onnxruntime-gpu 1.26. On a Turing (RTX 20) card
or newer it can move forward; see the note in `engine/pyproject.toml`.

## Calibrate the threshold

The engine decides "same person" by comparing a similarity score with a threshold. The one shipped
in `models.toml` is a conservative guess for the default model, and the engine reports
`calibrated: false` until you replace it with a measured one.

A threshold is only meaningful for the cameras and people it was measured on, so measure on yours.
This is separate from [tuning the kiosk camera](kiosk-camera.md), and comes after it.

1. **Collect consented photos** from the kiosk camera, in the light it will have:

    ```
    dataset/
      genuine/<person>/*.jpg     several photos of each person, at different times
      attacks/<kind>/*.jpg       optional: prints, phone screens… held up to the camera
    ```

    More people matters more than more photos each. A threshold for a false match rate of 1 in
    10,000 needs at least 10,000 pairs of photos of *different* people — about 50 people with three
    photos each. With fewer, the report says the estimate is rough.

2. **Run the evaluation on the build that serves traffic** — GPU and CPU produce slightly different
   scores. On the provider's host, with `COMPOSE_FILE` set as above:

    ```bash
    docker compose run --rm -v "$PWD/dataset:/data:ro" engine \
      python -m eval.run /data --out /tmp/reports
    ```

    On another machine it is the same `run` from `engine/deploy`, with `-f compose.gpu.yml` or
    `-f compose.cpu.yml`.

    It prints the threshold for the target false match rate (`--fmr`, default `1e-4`), the share of
    genuine attempts that threshold would reject, and how often each kind of attack passed the
    anti-spoofing model.

3. **Write the threshold into `engine/models.toml`** as `match_threshold`, set `calibrated = true`,
   and rebuild and restart the engine (`docker compose up -d --build engine`).

If too many genuine attempts are rejected at the threshold you need, improve the capture — light,
camera, distance — rather than lowering it. A lower threshold is a weaker lock.

## Change the model

1. Put the new model's file, checksum and calibrated threshold in `engine/models.toml`, and **change
   `version`**. Every stored face is stamped with the version it was enrolled under, and a face from
   another version is never compared — the person is told to enrol again.
2. Fetch the models, rebuild, restart: steps 3 and 5 of [On the provider's host](#on-the-providers-host).
3. If enrolment photos are kept (`IDEN_BIOMETRIC_KEEP_IMAGES=true`), move everyone onto the new
   model:

    ```bash
    docker compose exec provider python -m scripts.reembed_faces --dry-run
    docker compose exec provider python -m scripts.reembed_faces
    ```

    It reports how many faces had no photo and so can only move by enrolling again.

## Run it from source

For development, without Docker. The provider uses port 8000 and the docs site 8001:

```bash
cd engine
uv sync --extra cpu
uv run python -m scripts.fetch_models
ENGINE_TOKEN_FILE=../provider/keys/engine.token uv run uvicorn engine.app:app --port 8002
```

and point the provider at it with `IDEN_ENGINE_BASE_URL=http://localhost:8002`. The engine's own
checks run like the provider's: `uv run ruff format . && uv run ruff check . && uv run pyright &&
uv run pytest`. The tests that need the models are skipped until they are fetched.

To enrol a face in development, run the kiosk app against it on your laptop — see
[Kiosks](kiosks.md#develop-without-a-pi).

## When something is wrong

| Symptom | Cause |
|---|---|
| Sign-in shows *Face checks are unavailable right now* (`503 engine_unavailable`) | The provider cannot reach the engine, or the engine refused its token. Run the reachability check above; check `IDEN_ENGINE_BASE_URL`, and that both sides read the same `engine.token`. |
| The engine exits with `PermissionError` on `/secrets/engine.token` | The engine runs as uid 1000 and cannot read the token file, which is private to its owner. `sudo chown 1000 provider/keys/engine.token` (or `engine/deploy/engine.token`). The provider reads its keys as uid 1000 too. |
| The engine exits with `IsADirectoryError` on `/secrets/engine.token` | The token did not exist the first time the engine started, so Docker created an empty directory in its place. Remove that directory (`sudo rmdir provider/keys/engine.token`), generate the token, and start again. |
| The engine exits with `ENGINE_TOKEN_FILE must name a non-empty file in prod` | The token is missing on that machine: step 2 on the provider's host, or step 3 on another machine. |
| The engine exits saying a model file `is missing` | The models were not fetched into `engine/models` on the machine the engine runs on. |
| The engine exits saying a model `does not match the sha256` | A model file is not the reviewed one. Delete it and fetch again. |
| The engine exits with `ENGINE_DEVICE=cuda but onnxruntime cannot see a GPU` | The driver or the container toolkit is missing, or a GPU file is in use on a host without one. Run the `nvidia-smi` check above. |
| *Your face enrolment is out of date* (`409 face_enrolment_outdated`) | The model changed since this person enrolled. Re-embed, or have them enrol again. |
| No face section under Security, no Kiosks under Administration | The seed was not re-run after turning the module on, or you have not signed in again since. |
| Enrolment keeps failing at one kiosk | Usually the light or the camera settings. See [Tuning the kiosk camera](kiosk-camera.md#reading-the-results). |
