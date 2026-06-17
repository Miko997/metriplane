#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
source scripts/_vt_env.sh

echo "=== M8 provenance ==="
./tools/mp.sh preflight

echo
echo "=== Running provenance demo (./tools/mp.sh provenance) ==="
./tools/mp.sh provenance

# vt.sh chooses the run-id internally (e.g. provenance_run_001-4), so just find newest matching prefix.
RUN_DIR="$(vt_find_run_dir "provenance_run_001")"
echo "RUN_DIR=$RUN_DIR"

echo
echo "=== Show meta.json (top) ==="
sed -n '1,80p' "$RUN_DIR/meta.json"

echo
echo "=== Show session.jsonl header (first 2 lines) ==="
sed -n '1,2p' "$RUN_DIR/session.jsonl"

echo
echo "=== Evidence pointers (M8) ==="
echo "  run dir: $RUN_DIR"
echo "  meta:    $RUN_DIR/meta.json"
echo "  session: $RUN_DIR/session.jsonl"
echo "  env:     $RUN_DIR/env.txt"

echo
echo "=== Optional: hash meta.json (provenance evidence) ==="
sha256sum "$RUN_DIR/meta.json" || true
