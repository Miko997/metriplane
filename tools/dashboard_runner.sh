#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Compatibility wrapper for the capability-bearing Metriplane local launcher.
#
# Usage:
#   ./tools/dashboard_runner.sh [--port PORT] [--host HOST]

set -euo pipefail

# Default values
PORT=9000
HOST="127.0.0.1"
DASHBOARD_PORT="${WEB_PORT:-8088}"

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
            echo "Start the capability-bearing Metriplane local stack"
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

if [[ "$HOST" != "127.0.0.1" ]]; then
    echo "Runner only accepts the numeric IPv4 loopback bind address 127.0.0.1." >&2
    exit 64
fi

cd "$(dirname "$0")/.."
if [[ -x .venv/bin/python ]]; then
    PY=.venv/bin/python
else
    PY=python3
fi

echo "dashboard_runner.sh now starts the complete capability-bearing local stack."
echo "Preferred command: metriplane start"
exec "$PY" -m metriplane.cli start \
    --runner-port "$PORT" \
    --dashboard-port "$DASHBOARD_PORT"
