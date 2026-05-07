#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./tools/docker_clean.sh
docker compose --profile demo up -d --build
docker compose --profile demo ps
