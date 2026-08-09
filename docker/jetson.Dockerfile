# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Jetson / edge deployment image for Metriplane (replay-first).
#
# Default base is a slim Python image so the replay-only path builds anywhere.
# On Jetson hardware, override BASE_IMAGE with an L4T base that provides CUDA, e.g.:
#   docker build --build-arg BASE_IMAGE=nvcr.io/nvidia/l4t-base:r36.2.0 \
#     -f docker/jetson.Dockerfile -t metriplane-jetson .
# Keep the portable default immutable. Hardware-specific overrides should also
# use a tag plus manifest digest: image:tag@sha256:<digest>.
ARG BASE_IMAGE=python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal; add OpenCV/v4l libs only for the live-camera profile.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY metriplane ./metriplane
RUN pip install -U pip setuptools wheel && pip install -e .

# Metrics / WebSocket port
EXPOSE 8000

# Default to the bundled, camera-free incident demo.
CMD ["metriplane", "demo", "--out", "/tmp/metriplane-demo"]
