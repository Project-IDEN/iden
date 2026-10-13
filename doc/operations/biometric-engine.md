# The biometric engine

The engine is the one service that ever sees a face. It runs beside the provider, is reachable only
from it, keeps nothing between requests, and does the face work: finding the face, judging the
picture, checking it is live, and comparing it. What a face is for, and what is stored, is in
[Faces](../concepts/biometrics.md).

It is optional. Without it, and with `IDEN_BIOMETRIC_ENABLED=false`, IDEN is complete.

## Turn it on

1. **Generate the engine token**, if `provider/keys/engine.token` does not exist yet. The same
   command writes the signing and secret keys, and never overwrites one that exists:

    ```bash
    cd provider && uv run python -m scripts.gen_keys
    ```

2. **Fetch the models** into `engine/models`. About 360 MB, checked against the checksums in
   `engine/models.toml`:

    ```bash
    cd engine && uv sync --extra cpu && uv run python -m scripts.fetch_models
    ```

    Read the [model licences](../concepts/biometrics.md#the-models) before you go further.

3. **Turn the module on** in `deploy/.env`:

    ```bash
    IDEN_BIOMETRIC_ENABLED=true
    ```

4. **Start with the engine**, then re-run the seed so the face and kiosk permissions exist:

    ```bash
    docker compose -f deploy/docker-compose.yml --profile biometric up -d --build
    docker compose -f deploy/docker-compose.yml exec provider python -m scripts.seed
    ```

5. **Sign out of the dashboard and back in.** The face section appears under Security once your
   token carries `entity:face:read`, and Kiosks under Administration once it carries
   `admin:kiosks:read`.

6. **Set up a kiosk** — see [Kiosks](kiosks.md).

## On an NVIDIA GPU

On a GPU the engine checks a capture in a fraction of a second rather than a few seconds. The host
needs:

- an NVIDIA GPU from **Pascal (GTX 10-series) on**
- the NVIDIA driver, **575 or newer** — the image carries CUDA 12.9 and cuDNN 9
- the NVIDIA Container Toolkit

Check both with:

```bash
docker run --rm --gpus all nvidia/cuda:12.9.1-base-ubuntu24.04 nvidia-smi
```

The image stays on CUDA 12 deliberately. CUDA 13 dropped Maxwell, Pascal and Volta, and onnxruntime
moved to it from 1.27, so the GPU build is held at onnxruntime-gpu 1.26. On a Turing (RTX 20) card
or newer it can move forward; see the note in `engine/pyproject.toml`.

Then add the GPU overlay:

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml \
  --profile biometric up -d --build
```

The engine logs which device it chose when it starts:

```
Engine ready  calibrated=False device=cuda model_version=antelopev2-minifasnet-1
```

With the overlay, `ENGINE_DEVICE=cuda` makes the engine **refuse to start** when it cannot see a
GPU, instead of falling back to the CPU and serving twenty times slower without anyone noticing.

`IDEN_ENGINE_WORKERS` sets how many captures are checked at once. Each worker holds its own copy of
the models — up to about 1 GB of GPU memory — so size it to the card.

## Calibrate the threshold

The engine decides "same person" by comparing a similarity score with a threshold. The one shipped
in `models.toml` is a conservative guess for the default model, and the engine reports
`calibrated: false` until you replace it with a measured one.

A threshold is only meaningful for the cameras and people it was measured on, so measure on yours:

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
   scores:

    ```bash
    docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.gpu.yml \
      --profile biometric run --rm -v "$PWD/dataset:/data:ro" engine \
      python -m eval.run /data --out /tmp/reports
    ```

    It prints the threshold for the target false match rate (`--fmr`, default `1e-4`), the share of
    genuine attempts that threshold would reject, and how often each kind of attack passed the
    anti-spoofing models.

3. **Write the threshold into `engine/models.toml`** as `match_threshold`, set
    `calibrated = true`, and rebuild the engine. (`--write-threshold` does the editing when the
    evaluation runs from `engine/` on the host — use it only when the host is the serving build.)

If too many genuine attempts are rejected at the threshold you need, improve the capture — light,
camera, distance — rather than lowering it. A lower threshold is a weaker lock.

## Change the model

1. Put the new model's file, checksum and calibrated threshold in `engine/models.toml`, and **change
   `version`**. Every stored face is stamped with the version it was enrolled under, and a face from
   another version is never compared — the person is told to enrol again.
2. Fetch, rebuild, restart.
3. If enrolment photos are kept (`IDEN_BIOMETRIC_KEEP_IMAGES=true`), move everyone onto the new
   model:

    ```bash
    docker compose -f deploy/docker-compose.yml exec provider \
      python -m scripts.reembed_faces --dry-run
    docker compose -f deploy/docker-compose.yml exec provider python -m scripts.reembed_faces
    ```

    It reports how many faces had no photo and so can only move by enrolling again.

## Run it from source

For development, without Docker. The provider uses port 8000 and the docs site 8001:

```bash
cd engine
uv sync --extra cpu
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
| Sign-in shows *Face checks are unavailable right now* (`503 engine_unavailable`) | The provider cannot reach the engine, or the engine refused its token. Check the engine is running under `--profile biometric` and that both read the same `engine.token`. |
| *Your face enrolment is out of date* (`409 face_enrolment_outdated`) | The model changed since this person enrolled. Re-embed, or have them enrol again. |
| The engine exits with `ENGINE_DEVICE=cuda but onnxruntime cannot see a GPU` | The driver or the container toolkit is missing, or the GPU overlay is in use on a host without one. |
| The engine exits saying a model `does not match the sha256` | A model file is not the reviewed one. Delete it and fetch again. |
| Enrolment keeps failing with `not_live` at one kiosk | Usually the light: a window behind the person, or a screen too dim for the colour flashes to register. Each failure lists the checks that failed. |
