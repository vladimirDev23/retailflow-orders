# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv

FROM python:3.13.14-slim-bookworm AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM python:3.13.14-slim-bookworm
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN groupadd --system retailflow \
    && useradd --system --gid retailflow --home-dir /app retailflow
WORKDIR /app
COPY --from=builder --chown=retailflow:retailflow /app/.venv .venv
COPY --chown=retailflow:retailflow alembic alembic
COPY --chown=retailflow:retailflow dev_support dev_support
COPY --chown=retailflow:retailflow docker docker
COPY --chown=retailflow:retailflow scripts scripts
COPY --chown=retailflow:retailflow src src
COPY --chown=retailflow:retailflow alembic.ini pyproject.toml README.md ./
USER retailflow
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=2)" || exit 1
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api"]
