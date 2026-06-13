#!/usr/bin/env bash
# Start the Metriplane operator UI: the runner API (port 9000) + the dashboard
# static server (port 8088). Run this in your own terminal; Ctrl-C stops both.
#
#   ./tools/command_center_up.sh
#   → open http://localhost:8088/command_center_live.html
set -euo pipefail
cd "$(dirname "$0")/.."

RUNNER_PORT="${RUNNER_PORT:-9000}"
WEB_PORT="${WEB_PORT:-8088}"

# Use the venv python if present.
if [ -x ".venv/bin/python" ]; then PY=".venv/bin/python"; else PY="python3"; fi

# Free the ports if something is already listening.
pkill -f "metriplane.runner.service --host 127.0.0.1 --port ${RUNNER_PORT}" 2>/dev/null || true
pkill -f "http.server ${WEB_PORT}" 2>/dev/null || true
sleep 0.3

echo "[command-center] starting runner on http://127.0.0.1:${RUNNER_PORT}"
"$PY" -m metriplane.runner.service --host 127.0.0.1 --port "${RUNNER_PORT}" &
RUNNER_PID=$!

echo "[command-center] serving dashboard on http://127.0.0.1:${WEB_PORT}"
"$PY" -m http.server "${WEB_PORT}" --directory web/dashboard &
WEB_PID=$!

cleanup() { echo; echo "[command-center] stopping…"; kill "$RUNNER_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup INT TERM EXIT

sleep 1
echo
echo "  Open:  http://localhost:${WEB_PORT}/command_center_live.html"
echo "  (Operator setup, runtime console, and system dashboard are linked in the bottom nav.)"
echo "  Press Ctrl-C to stop."
echo
wait
