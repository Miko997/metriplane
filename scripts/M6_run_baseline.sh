#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
source scripts/_vt_env.sh

echo "=== M6 baseline ==="
./tools/mp.sh preflight

RUN_ID="m6_fusion_cpu_$(date +%Y%m%d_%H%M%S)"
DUR_S="${1:-10}"

echo
echo "=== Running fusion (CPU) for ${DUR_S}s; run-id=${RUN_ID} ==="
./tools/mp.sh run-fusion cpu "$DUR_S" "$RUN_ID"

RUN_DIR="$(vt_find_run_dir "$RUN_ID")"
echo "RUN_DIR=$RUN_DIR"

echo
echo "=== Offline session health summary (no HTTP) ==="
python tools/session_health_summary.py "$RUN_DIR/session.jsonl"

echo
echo "=== Evidence pointers (M6) ==="
echo "  session: $RUN_DIR/session.jsonl"
echo "  meta:    $RUN_DIR/meta.json"
echo "  env:     $RUN_DIR/env.txt"
echo
echo "First 2 lines of session.jsonl:"
sed -n '1,2p' "$RUN_DIR/session.jsonl"
