#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
cd "$(dirname "$0")/.."

# Hard reset: stop/remove containers + remove volumes.
#
# NOTE: If you were recording MP4s (live mode), prefer ./tools/docker_stop.sh first.
# It sends SIGINT to let VideoWriter finalize output.

# Attempt a graceful stop first (safe even if nothing is running)
./tools/docker_stop.sh || true

# Remove volumes (this clears vt_data)
docker compose --profile demo --profile dummy --profile live down --remove-orphans --volumes || true

# Safety net: only remove containers owned by this Compose project. Never
# remove an unrelated container merely because it publishes a Metriplane port.
docker ps -q --filter "label=com.docker.compose.project=metriplane-core" \
  | xargs -r docker rm -f || true

ss -lntp | egrep ':8000|:8765' || true
