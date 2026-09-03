FROM python:3.11-slim

# curl for the healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer — cached unless pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Source + runtime config read at startup (field_manager loads field_configs.yaml)
COPY src/ ./src/
COPY field_configs.yaml ./
COPY scripts/ ./scripts/
RUN uv sync --frozen --no-dev

# M-15: run as a non-root uid. The container mounts the shared auth DB and
# writes the Fernet link key and the link cache into that bind mount, so root
# here is a blast-radius multiplier over cross-server credentials rather than
# a hygiene item. uid 1000 matches the host owner of the shared data dir;
# override with --build-arg APP_UID=... if yours differs.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home app \
    && mkdir -p /app/data \
    && chown -R "${APP_UID}:${APP_GID}" /app
USER app

ENV FASTMCP_TRANSPORT=http
ENV FASTMCP_HOST=0.0.0.0
ENV FASTMCP_PORT=8005
# cluster ports: citations 8002, pfw 8003, ptab 8004, fpd 8005

# MCP port. The download proxy (FPD_PROXY_PORT, default 8081) is a
# localhost-only fallback — downloads resolve through the PFW centralized
# proxy (set CENTRALIZED_PROXY_URL); do not publish the proxy port.
EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD curl -sf "http://localhost:${FASTMCP_PORT:-8005}/health" || exit 1

CMD ["uv", "run", "fpd-mcp"]
