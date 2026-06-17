#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
cd "$(dirname "$0")/.."

./tools/docker_clean.sh
docker compose --profile live up -d --build

docker compose --profile live ps
docker compose --profile live logs --tail=80 metriplane_live || true
