# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Immutable manifest-list digest; Dependabot keeps the reference current.
FROM python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    METRIPLANE_DATA_DIR=/data

RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      libgl1 \
      libglib2.0-0 \
      libpcre2-8-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash metriplane

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel

COPY . /app
# The Docker build context intentionally excludes .git. Install the copied runtime
# source in editable mode so the release-wheel backend never invents a Git identity.
RUN pip install -e .

# Build/install tooling is not part of the runtime attack surface. Removing pip
# also removes its vendored dependency SBOM; ensurepip would otherwise retain an
# older bundled pip wheel alongside the upgraded installation.
RUN pip uninstall --yes pip setuptools wheel \
 && rm -rf /usr/local/lib/python3.12/ensurepip

# IMPORTANT:
# Create /data in the IMAGE and chown it.
# When a named volume mounts here for the first time, Docker copies ownership metadata.
RUN mkdir -p /data/runs /data/datasets /data/evidence \
 && chown -R metriplane:metriplane /data

USER metriplane

EXPOSE 8000 8765

# Docker/Compose stops containers with a signal. Default is SIGTERM, but Metriplane currently
# handles SIGINT (Ctrl+C) reliably for flushing video writers. Use SIGINT as stop signal.
STOPSIGNAL SIGINT

ENTRYPOINT ["metriplane"]
CMD ["--help"]
