# syntax=docker/dockerfile:1

# The kiosk server with the kiosk client built into it. Everything it needs is
# in kiosk/, which is the build context:
#
#     docker buildx build --platform linux/arm64,linux/amd64 \
#       --build-arg VERSION=$(git describe --always) -t <registry>/iden-kiosk --push kiosk

FROM node:22-alpine AS client
RUN corepack enable
WORKDIR /app
COPY client/package.json client/pnpm-lock.yaml client/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY client/ .
RUN pnpm build


FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS server
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY server/pyproject.toml server/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev
COPY server/ .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-slim-trixie

ARG VERSION=dev
RUN useradd --create-home --uid 1000 kiosk && install -d -o kiosk -g kiosk /data
WORKDIR /app
COPY --from=server --chown=kiosk:kiosk /app /app
COPY --from=client /app/dist /app/ui
ENV PATH="/app/.venv/bin:$PATH" \
    KIOSK_ENV=prod \
    KIOSK_VERSION=$VERSION \
    KIOSK_DATA_DIR=/data \
    KIOSK_UI_DIR=/app/ui
USER kiosk
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/state')"
# 0.0.0.0 inside the container; compose publishes it on the host's loopback only.
CMD ["uvicorn", "kiosk_server.app:app", "--host", "0.0.0.0", "--port", "8080"]
