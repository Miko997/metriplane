#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

WITH_LIVE=0
if [[ "${1:-}" == "--live" ]]; then
  WITH_LIVE=1
  shift
fi

BASE_CFG="${1:-configs/examples/config.m6_board_110x40_warehouse_story_v1_live_002.yaml}"
PROFILE="${2:-board_110x40_warehouse_story_v1}"

echo "== Environment =="
python -V
python -m pip -V

echo
echo "== Editable install =="
python -m pip install -e .

echo
echo "== Import path sanity (must be metriplane.run package module) =="
python - <<'PY'
import importlib.util
spec = importlib.util.find_spec("metriplane.run")
print("metriplane.run ->", spec.origin)
PY

echo
echo "== Unit tests (covers schema/mapping/zones/record-replay) =="
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q

echo
echo "== Offline determinism: M6 JSONL -> CSV matches live exports (if present) =="
bash tools/verify_m6_offline.sh

if [[ "$WITH_LIVE" -eq 0 ]]; then
  echo
  echo "DONE (offline proof). To also prove camera+live WS+metrics, run:"
  echo "  bash tools/verify_m1_m6.sh --live"
  exit 0
fi

echo
echo "== Live proof: short run (camera required) =="
if [[ ! -f "$BASE_CFG" ]]; then
  echo "ERROR: base config not found: $BASE_CFG"
  exit 2
fi

# Build a temporary config so we never overwrite evidence files.
eval "$(BASE_CFG="$BASE_CFG" python - <<'PY'
import os, time
from pathlib import Path
import yaml

base = Path(os.environ["BASE_CFG"])
data = yaml.safe_load(base.read_text(encoding="utf-8"))

stamp = time.strftime("%Y%m%d_%H%M%S")
jsonl = Path("evidence/sessions") / f"_verify_live_{stamp}.jsonl"
video = Path("evidence/demos") / f"_verify_live_{stamp}.mp4"
analytics = Path("evidence/analytics") / f"_verify_live_{stamp}"

# Ensure dirs exist
jsonl.parent.mkdir(parents=True, exist_ok=True)
video.parent.mkdir(parents=True, exist_ok=True)
analytics.mkdir(parents=True, exist_ok=True)

# Override paths safely
data["record_jsonl"] = str(jsonl)
data["analytics_out_dir"] = str(analytics)

# Only enable video if base config already had it truthy
if data.get("record_video"):
    data["record_video"] = str(video)

tmp = Path(f"/tmp/metriplane_verify_{stamp}.yaml")
tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

print(f'VERIFY_CFG="{tmp}"')
print(f'VERIFY_JSONL="{jsonl}"')
print(f'VERIFY_ANALYTICS="{analytics}"')
print(f'VERIFY_VIDEO="{video}"')
PY
)"

LOG1="${VERIFY_CFG%.yaml}.run1.log"
LOG2="${VERIFY_CFG%.yaml}.run2.log"

RUN_CMD=(metriplane --config "$VERIFY_CFG")
echo "[run] ${RUN_CMD[*]}"
"${RUN_CMD[@]}" >"$LOG1" 2>&1 &
PID=$!

# Give the server a moment to start
sleep 1.2

# WS smoke (M2 proof)
python tools/ws_smoke_client.py --url ws://127.0.0.1:8765 --n 3 --timeout 3.0

# Metrics endpoint smoke (M4 proof)
if command -v curl >/dev/null; then
  curl -sf http://127.0.0.1:8000/metrics >/dev/null
  echo "[metrics] OK (endpoint responds)"
else
  echo "[metrics] SKIP (curl not installed)"
fi

# Stop cleanly
kill -INT "$PID" || true
wait "$PID" || true

# Recording sanity (M2 proof)
test -s "$VERIFY_JSONL"
FRAME1="$(head -n 1 "$VERIFY_JSONL" | sed 's/.*"frame_id": \([0-9]\+\).*/\1/' || true)"
echo "[jsonl] first frame_id=$FRAME1 lines=$(wc -l < "$VERIFY_JSONL") path=$VERIFY_JSONL"
if [[ "$FRAME1" != "1" ]]; then
  echo "ERROR: expected frame_id=1, got $FRAME1"
  exit 2
fi

# Second run should WARN about overwrite (your new behavior)
"${RUN_CMD[@]}" >"$LOG2" 2>&1 &
PID2=$!
sleep 0.8
kill -INT "$PID2" || true
wait "$PID2" || true

if grep -q "WILL BE OVERWRITTEN" "$LOG2"; then
  echo "[overwrite-warning] OK (found in logs)"
else
  echo "ERROR: overwrite warning NOT found. Log: $LOG2"
  exit 2
fi

# M6 proof: offline regen matches live export for THIS short run
OFF_DIR="${VERIFY_ANALYTICS}_offline_regen"
mkdir -p "$OFF_DIR"

python tools/zones_report_jsonl.py \
  "$VERIFY_JSONL" \
  --profile "$PROFILE" \
  --out "$OFF_DIR" \
  --prefix m6

for f in m6_zone_events.csv m6_zone_dwell.csv m6_zone_dwell_by_zone.csv m6_zone_transitions.csv; do
  diff -u "$VERIFY_ANALYTICS/$f" "$OFF_DIR/$f"
done

echo
echo "ALL OK: live short-run + WS + metrics + overwrite-warning + M6 determinism proven."
echo "Artifacts:"
echo "  config:   $VERIFY_CFG"
echo "  jsonl:    $VERIFY_JSONL"
echo "  analytics $VERIFY_ANALYTICS"
echo "  log1:     $LOG1"
echo "  log2:     $LOG2"
