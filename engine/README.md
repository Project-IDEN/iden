# IDEN biometric engine

The internal service that analyses faces for IDEN: detection, a quality gate that says what to fix,
liveness (an anti-spoofing model, random head movements, one face throughout),
and 1:1 comparison. Stateless — the provider sends frames and, to verify, the templates; nothing
outlives the request. Reached only by the provider — on the same host, or on another machine.

Self-contained: `engine/` needs nothing else in the repository, so it can be deployed alone.

| | |
|---|---|
| `Dockerfile` | `cpu` and `gpu` targets. `engine/` is the build context. |
| `deploy/compose.cpu.yml`, `deploy/compose.gpu.yml` | The engine on a machine of its own, on the CPU or an NVIDIA GPU. On the provider's host, `deploy/docker-compose.engine-*.yml` at the root run it instead. |

```bash
uv sync --extra cpu                     # or --extra gpu on an NVIDIA host
uv run python -m scripts.fetch_models   # ~290 MB, checked against models.toml
ENGINE_TOKEN_FILE=../provider/keys/engine.token uv run uvicorn engine.app:app --port 8002
```

Checks, from `engine/`: `uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest`.
Tests that need the models are skipped until they are fetched.

`models.toml` pins each model by checksum and holds the thresholds calibrated for it; `eval/` measures
them on your own images. **The default models' licences are non-commercial.**

- What a face is for and what it does not stop: [doc/concepts/biometrics.md](../doc/concepts/biometrics.md)
- Running it, on a GPU, on another machine, calibrating it: [doc/operations/biometric-engine.md](../doc/operations/biometric-engine.md)
