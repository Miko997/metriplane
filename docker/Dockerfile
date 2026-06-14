# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    METRIPLANE_DATA_DIR=/data

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      git \
      libgl1 \
      libglib2.0-0 \
      libsm6 \
      libxext6 \
      libxrender1 \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash metriplane

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel

COPY . /app
RUN pip install .

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
