#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Graceful stop that preserves volumes.
#
# Why SIGINT?
# - SIGINT (Ctrl+C) reliably triggers Metriplane's clean shutdown path and
#   closes OpenCV VideoWriter, so MP4 files have a valid 'moov' atom.
# - SIGTERM may not be handled in some runs, which can corrupt MP4 outputs.

# Ask services to shut down (ignore errors if a service isn't running)
docker compose --profile demo --profile dummy --profile live kill -s SIGINT metriplane_demo 2>/dev/null || true
docker compose --profile demo --profile dummy --profile live kill -s SIGINT metriplane_dummy 2>/dev/null || true
docker compose --profile demo --profile dummy --profile live kill -s SIGINT metriplane_live 2>/dev/null || true

# Give the app a moment to flush/close files
sleep 2

# Remove containers/networks, keep volumes
docker compose --profile demo --profile dummy --profile live down --remove-orphans || true
