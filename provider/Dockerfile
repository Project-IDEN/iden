# syntax=docker/dockerfile:1

# Dependencies are installed in their own stage and copied forward, so the
# runtime image carries no uv, no build tools, and no lockfile.
FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies before source: the layer is rebuilt only when the lock changes,
# not on every edit to a route.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.15.0-slim-trixie

# Not root. A container that is compromised should not also be privileged.
RUN useradd --create-home --uid 1000 iden
WORKDIR /app

COPY --from=builder --chown=iden:iden /app /app
ENV PATH="/app/.venv/bin:$PATH"

USER iden
EXPOSE 8000

# The liveness probe, so a wedged process is restarted. Readiness is the
# orchestrator's job — Compose has no way to drain traffic, so checking
# dependencies here would only stop the container that reports them.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

CMD ["provider"]
