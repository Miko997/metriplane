#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# tools/start_metriplane.sh — Metriplane one-command launcher (no venv activation required)
#
# Usage (from any directory, no `source .venv/bin/activate` needed):
#   ./tools/start_metriplane.sh [args...]
#   ./tools/start_metriplane.sh --open
#   ./tools/start_metriplane.sh --live --config configs/fusion_health_300fps.yaml --open
#   ./tools/start_metriplane.sh --operator
#   ./tools/start_metriplane.sh stop
#   ./tools/start_metriplane.sh status
#   ./tools/start_metriplane.sh cleanup
#
# Passes all arguments through to `metriplane start` by default,
# or to `metriplane <subcommand>` if first arg is stop/restart/status/cleanup/doctor.
#
# Requires:
#   .venv/bin/python  — created by `python3 -m venv .venv && pip install -e .`

set -euo pipefail

# Resolve repo root (directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

PYTHON="$REPO_ROOT/.venv/bin/python"

# Check if venv exists
if [[ ! -x "$PYTHON" ]]; then
    echo "❌ .venv not found at $REPO_ROOT/.venv"
    echo ""
    echo "Set up the virtual environment first:"
    echo "  cd $REPO_ROOT"
    echo "  python3 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -e ."
    echo ""
    echo "Then retry: ./tools/start_metriplane.sh $*"
    exit 1
fi

# Dispatch: if first arg is a known subcommand, pass verbatim; otherwise default to 'start'
FIRST="${1:-}"
case "$FIRST" in
    stop|restart|status|cleanup|doctor|replay)
        exec "$PYTHON" -m metriplane.cli "$@"
        ;;
    start)
        exec "$PYTHON" -m metriplane.cli "$@"
        ;;
    *)
        # Default: treat all args as arguments to 'start'
        exec "$PYTHON" -m metriplane.cli start "$@"
        ;;
esac
