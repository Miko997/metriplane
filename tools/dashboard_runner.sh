#!/usr/bin/env bash
# Start Metriplane Dashboard Runner Service
#
# Usage:
#   ./tools/dashboard_runner.sh [--port PORT] [--host HOST]

set -euo pipefail

# Default values
PORT=9000
HOST="127.0.0.1"

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

echo "Starting Metriplane Dashboard Runner..."
echo "Port: $PORT"
echo "Host: $HOST"
echo ""

# Run the service
python -m metriplane.runner.service --host "$HOST" --port "$PORT"
