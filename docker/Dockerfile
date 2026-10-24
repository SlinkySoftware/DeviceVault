# DeviceVault Python images. Build from the repository root:
#   docker build -f docker/Dockerfile --target orchestrator -t devicevault-orchestrator .
#   docker build -f docker/Dockerfile --target worker       -t devicevault-worker .
#   docker build -f docker/Dockerfile --target receiver     -t devicevault-receiver .
#   docker build -f docker/Dockerfile --target dev          -t devicevault-dev .

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv

FROM python:3.14-slim-trixie AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH=/opt/venv/bin:$PATH
RUN useradd --system --uid 10001 --create-home --home-dir /var/lib/devicevault devicevault

# Workspace metadata only, so dependency layers survive source changes.
# python-ldap ships no wheels, so it is compiled against OpenLDAP and SASL here.
FROM base AS lock
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev libldap-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY protocol/pyproject.toml protocol/
COPY worker/pyproject.toml worker/
COPY receiver/pyproject.toml receiver/
COPY orchestrator/pyproject.toml orchestrator/

FROM lock AS build-orchestrator
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package devicevault-orchestrator
COPY protocol protocol
COPY worker worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package devicevault-orchestrator

FROM lock AS build-worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package devicevault-worker
COPY protocol protocol
COPY worker worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package devicevault-worker

FROM lock AS build-receiver
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package devicevault-receiver
COPY protocol protocol
COPY receiver receiver
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package devicevault-receiver

# --- Orchestrator: api, result consumers, worker monitor, flower ---------------
FROM base AS orchestrator
RUN apt-get update && apt-get install -y --no-install-recommends libldap2 libsasl2-2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build-orchestrator /opt/venv /opt/venv
COPY orchestrator /app
WORKDIR /app
RUN DV_DEBUG=true python manage.py collectstatic --noinput --verbosity 0
COPY docker/orchestrator-entrypoint.sh /usr/local/bin/dv-orchestrator
ENV DV_DATA_DIR=/var/lib/devicevault
USER devicevault
EXPOSE 8000
ENTRYPOINT ["dv-orchestrator"]
CMD ["api"]

# --- Worker: collection or storage, no Django ----------------------------------
FROM base AS worker
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o devicevault -g devicevault /srv/devicevault
COPY --from=build-worker /opt/venv /opt/venv
COPY docker/worker-entrypoint.sh /usr/local/bin/dv-worker
WORKDIR /var/lib/devicevault
USER devicevault
VOLUME ["/var/lib/devicevault"]
ENTRYPOINT ["dv-worker"]

# --- Receiver: accepts backups devices push (SCP/SFTP), no Django or Celery pool -
FROM base AS receiver
COPY --from=build-receiver /opt/venv /opt/venv
COPY docker/receiver-entrypoint.sh /usr/local/bin/dv-receiver
WORKDIR /var/lib/devicevault
USER devicevault
VOLUME ["/var/lib/devicevault"]
ENTRYPOINT ["dv-receiver"]

# --- Dev: every package's dependencies plus dev tools; source is bind-mounted --
FROM lock AS dev
# Dev containers run as the host user (any UID), so the storage root and the
# worker state directory are world-writable and sticky here; the worker image
# owns them as devicevault.
RUN apt-get update && apt-get install -y --no-install-recommends git make \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 1777 /srv/devicevault \
    && chmod 1777 /var/lib/devicevault
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-install-workspace \
    && printf '/workspace/protocol/src\n/workspace/worker/src\n/workspace/receiver/src\n' \
       > /opt/venv/lib/python3.14/site-packages/devicevault-workspace.pth
COPY docker/orchestrator-entrypoint.sh /usr/local/bin/dv-orchestrator
COPY docker/worker-entrypoint.sh /usr/local/bin/dv-worker
COPY docker/receiver-entrypoint.sh /usr/local/bin/dv-receiver
WORKDIR /workspace/orchestrator
