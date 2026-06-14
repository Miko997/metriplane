#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Compatibility wrapper for the single-command Metriplane launcher.
#
#   ./tools/command_center_up.sh
#   -> opens http://localhost:8088/web/dashboard/index.html
set -euo pipefail
cd "$(dirname "$0")/.."

RUNNER_PORT="${RUNNER_PORT:-9000}"
WEB_PORT="${WEB_PORT:-8088}"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "[metriplane] starting local console with one command"
echo "[metriplane] preferred command: metriplane start"
exec "$PY" -m metriplane.cli start \
  --runner-port "${RUNNER_PORT}" \
  --dashboard-port "${WEB_PORT}"
