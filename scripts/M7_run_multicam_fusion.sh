#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
source scripts/_vt_env.sh

echo "=== M7 multi-cam fusion (cam0+cam1) ==="
./tools/mp.sh preflight

RUN_ID="m7_fusion_cpu_$(date +%Y%m%d_%H%M%S)"
DUR_S="${1:-10}"

echo
echo "=== Running fusion (CPU) for ${DUR_S}s; run-id=${RUN_ID} ==="
./tools/mp.sh run-fusion cpu "$DUR_S" "$RUN_ID"

RUN_DIR="$(vt_find_run_dir "$RUN_ID")"
echo "RUN_DIR=$RUN_DIR"

echo
echo "=== Offline session health summary (cam presence, age, stale-for-fusion) ==="
python tools/session_health_summary.py "$RUN_DIR/session.jsonl"

echo
echo "=== Quick check: count frames where cam1 was marked stale_for_fusion ==="
# IMPORTANT: pass args BEFORE the heredoc redirection
python - "$RUN_DIR" <<'PY'
import json, sys
from pathlib import Path

run_dir = Path(sys.argv[1])
p = run_dir / "session.jsonl"

stale = 0
present = 0
frames = 0

with p.open(encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("type") == "run_header":
            continue
        frames += 1
        for cam in (r.get("raw_per_camera") or []):
            if cam.get("camera_id") == "cam1":
                present += 1
                if cam.get("metrics", {}).get("stale_for_fusion"):
                    stale += 1

pct = (stale / present * 100.0) if present else 0.0
print(f"frames={frames} cam1_present_frames={present} cam1_stale_frames={stale} cam1_stale_pct={pct:.2f}%")
PY

echo
echo "=== Evidence pointers (M7) ==="
echo "  session: $RUN_DIR/session.jsonl"
echo "  meta:    $RUN_DIR/meta.json"
echo "  env:     $RUN_DIR/env.txt"
