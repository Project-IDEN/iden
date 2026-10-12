# syntax=docker/dockerfile:1

# Two targets, one per onnxruntime build:
#
#     docker build --target cpu .   # any machine, including a laptop
#     docker build --target gpu .   # NVIDIA host, Pascal (GTX 10) or newer
#
# Model files are not in either image. They are mounted read-only at
# /app/models, fetched once with `python -m scripts.fetch_models`.

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS cpu-builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --extra cpu
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra cpu


FROM python:3.14-slim-trixie AS cpu

RUN useradd --create-home --uid 1000 iden
WORKDIR /app
COPY --from=cpu-builder --chown=iden:iden /app /app
ENV PATH="/app/.venv/bin:$PATH" ENGINE_DEVICE=cpu
USER iden
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"
CMD ["engine"]


# CUDA 12 and cuDNN 9, which onnxruntime-gpu 1.26 is built against. CUDA 12
# rather than 13 because 13 cannot run on Pascal (GTX 10) or older. The host
# needs only the NVIDIA driver and the container toolkit; the libraries are here.
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04 AS gpu

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/python
# The base image ships a user at uid 1000; the key files are owned by that uid.
RUN userdel --remove ubuntu && useradd --create-home --uid 1000 iden
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev --extra gpu
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra gpu \
    && chown -R iden:iden /app /opt/python
ENV PATH="/app/.venv/bin:$PATH" ENGINE_DEVICE=cuda
USER iden
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"
CMD ["engine"]
