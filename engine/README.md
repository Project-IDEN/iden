# IDEN biometric engine

The internal service that analyses faces for IDEN: detection, a quality gate that says what to fix,
liveness (anti-spoofing models, random head movements, random screen colours, one face throughout),
and 1:1 comparison. Stateless — the provider sends frames and, to verify, the templates; nothing
outlives the request. Never exposed outside the deployment.

```bash
uv sync --extra cpu                     # or --extra gpu on an NVIDIA host
uv run python -m scripts.fetch_models   # ~360 MB, checked against models.toml
ENGINE_TOKEN_FILE=../provider/keys/engine.token uv run uvicorn engine.app:app --port 8002
```

Checks, from `engine/`: `uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest`.
Tests that need the models are skipped until they are fetched.

`models.toml` pins each model by checksum and holds the thresholds calibrated for it; `eval/` measures
them on your own images. **The default recogniser's licence is non-commercial.**

- What a face is for and what it does not stop: [doc/concepts/biometrics.md](../doc/concepts/biometrics.md)
- Running it, on a GPU, calibrating it: [doc/operations/biometric-engine.md](../doc/operations/biometric-engine.md)
