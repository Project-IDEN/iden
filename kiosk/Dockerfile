# syntax=docker/dockerfile:1

# The kiosk server with the kiosk UI built into it. Built from the repository
# root, because the UI is a workspace package beside the dashboard:
#
#     docker buildx build -f kiosk/Dockerfile --platform linux/arm64,linux/amd64 \
#       --build-arg VERSION=$(git describe --always) -t <registry>/iden-kiosk --push .

FROM node:22-alpine AS ui
RUN corepack enable
WORKDIR /app
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/tsconfig.base.json ./
COPY web/shared/package.json shared/
COPY web/kiosk/package.json kiosk/
RUN pnpm install --frozen-lockfile --filter @iden/kiosk...
COPY web/shared/ shared/
COPY web/kiosk/ kiosk/
RUN pnpm --filter @iden/kiosk build


FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS server
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY kiosk/server/pyproject.toml kiosk/server/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev
COPY kiosk/server/ .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.14-slim-trixie

ARG VERSION=dev
RUN useradd --create-home --uid 1000 kiosk && install -d -o kiosk -g kiosk /data
WORKDIR /app
COPY --from=server --chown=kiosk:kiosk /app /app
COPY --from=ui /app/kiosk/dist /app/ui
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
