#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Start Metriplane Dashboard Runner Service
#
# Usage:
#   ./tools/dashboard_runner.sh [--port PORT] [--host HOST]

set -euo pipefail

# Default values
PORT=9000
HOST="127.0.0.1"
STATUS_HOST="127.0.0.1"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--port PORT] [--host HOST]"
            echo ""
            echo "Start Metriplane Dashboard Runner Service"
            echo ""
            echo "Options:"
            echo "  --port PORT    Port number (default: 9000)"
            echo "  --host HOST    Bind address (default: 127.0.0.1)"
            echo "  --help         Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [[ "$HOST" == "0.0.0.0" || "$HOST" == "::" ]]; then
    STATUS_HOST="127.0.0.1"
else
    STATUS_HOST="$HOST"
fi

runner_status() {
    python - "$STATUS_HOST" "$PORT" <<'PY'
import json
import sys
import urllib.error
import urllib.request

host = sys.argv[1]
port = int(sys.argv[2])
url = f"http://{host}:{port}/status"

try:
    with urllib.request.urlopen(url, timeout=0.5) as response:
        data = json.loads(response.read().decode("utf-8"))
except Exception:
    raise SystemExit(1)

print(data.get("status", "unknown"))
PY
}

check_port_available() {
    python - "$HOST" "$PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
PY
}

echo "Starting Metriplane Dashboard Runner..."
echo "Port: $PORT"
echo "Host: $HOST"
echo ""

if status="$(runner_status 2>/dev/null)"; then
    echo "Metriplane Dashboard Runner is already running."
    echo "Runner API: http://$STATUS_HOST:$PORT/status"
    echo "Status: $status"
    echo ""
    echo "Use the existing runner, or stop the full local stack with:"
    echo "  python -m metriplane.cli stop"
    exit 0
fi

if ! port_error="$(check_port_available 2>&1)"; then
    echo "Port $PORT is already in use, but it did not answer as a Metriplane runner."
    echo "Bind error: $port_error"
    echo ""
    echo "Inspect what is running:"
    echo "  python -m metriplane.cli status"
    echo ""
    echo "Remove orphaned Metriplane services on known ports:"
    echo "  python -m metriplane.cli cleanup"
    echo ""
    echo "Or start this runner on another port:"
    echo "  ./tools/dashboard_runner.sh --port $((PORT + 1))"
    exit 98
fi

# Run the service
python -m metriplane.runner.service --host "$HOST" --port "$PORT"
