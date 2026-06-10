#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-board_55x40_warehouse_story_v1_fusion}"
CFG="${2:-configs/examples/config.m8_fusion_55x40_live.yaml}"
DUR="${DUR:-15}"

RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT="evidence/proofs/m8_${RUN_ID}"
mkdir -p "$OUT"

# Force profile for apply_profile_defaults()
mkdir -p calib
printf "profile: %s\n" "$PROFILE" > calib/active_profile.yaml

# Kill any stale camera users
fuser -k /dev/video0 /dev/video2 >/dev/null 2>&1 || true

# Headless proof (no GUI windows)
export METRIPLANE_SHOW_PREVIEW="${METRIPLANE_SHOW_PREVIEW:-0}"

echo "[proof] starting fusion..."
python tools/run_fusion_yaml.py "$CFG" >"$OUT/fusion.log" 2>&1 &
FUSION_PID=$!

# Wait for WS
for _ in $(seq 1 120); do
  if ss -lntp 2>/dev/null | grep -q "127.0.0.1:8765"; then break; fi
  sleep 0.1
done

if ! ss -lntp 2>/dev/null | grep -q "127.0.0.1:8765"; then
  echo "[proof] FAIL: WS not up"
  tail -n 120 "$OUT/fusion.log" || true
  exit 1
fi

echo "[proof] run for ${DUR}s..."
sleep "$DUR"

echo "[proof] stopping fusion..."
kill "$FUSION_PID" >/dev/null 2>&1 || true
sleep 0.8

# Copy newest session JSONL
SESSION="$(ls -1t evidence/sessions/*.jsonl 2>/dev/null | head -n1 || true)"
if [[ -z "${SESSION}" ]]; then
  echo "[proof] FAIL: no session jsonl found in evidence/sessions/"
  exit 1
fi
cp "$SESSION" "$OUT/session.jsonl"

# ---- Alignment (live, uses profile files) ----
PROFILE_DIR="calib/profiles/$PROFILE"
BOUNDS="${BOUNDS:-"-0.05,0.60,-0.05,0.45"}"

CAM0_DEV="${CAM0_DEV:-/dev/v4l/by-id/usb-XIFT_Streaming_Webcams_2025072203-video-index0}"
CAM1_DEV="${CAM1_DEV:-/dev/v4l/by-id/usb-SunplusIT_Inc_HP_320_FHD_Webcam_YJGD325HP20211201V0-video-index0}"

CAM0_IDX="$(python -c "from metriplane.camera.v4l_resolve import resolve_v4l_to_index as r; print(r('$CAM0_DEV'))")"
CAM1_IDX="$(python -c "from metriplane.camera.v4l_resolve import resolve_v4l_to_index as r; print(r('$CAM1_DEV'))")"

echo "[proof] alignment: cam0=$CAM0_IDX cam1=$CAM1_IDX bounds=$BOUNDS" | tee "$OUT/alignment.txt"

python tools/debug_alignment.py \
  --cam0 "$CAM0_IDX" --cam1 "$CAM1_IDX" \
  --mapping-cam0 "$PROFILE_DIR/cam0/mapping_raw.yaml" \
  --mapping-cam1 "$PROFILE_DIR/cam1/mapping_raw.yaml" \
  --intrinsics-cam0 "$PROFILE_DIR/cam0/camera.yaml" \
  --intrinsics-cam1 "$PROFILE_DIR/cam1/camera.yaml" \
  --anchors "$PROFILE_DIR/anchors.yaml" \
  --bounds="$BOUNDS" \
  --seconds "${ALIGN_SECONDS:-8}" \
  >> "$OUT/alignment.txt" 2>&1 || true

if [[ -f benchmarks/run_fusion_jitter.py ]]; then
  python benchmarks/run_fusion_jitter.py "$OUT/session.jsonl" --out "$OUT/jitter_coverage.csv"
else
  echo "[proof] WARN: benchmarks/run_fusion_jitter.py missing (no jitter csv)"
fi

echo "[proof] OK: artifacts in $OUT"
