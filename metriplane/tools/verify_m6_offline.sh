#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python -m pip install -e . >/dev/null

# Known M6 sessions to verify (skip if missing)
CASES=(
  "board_110x40_warehouse_story_v1:evidence/sessions/m6_board_110x40_warehouse_story_v1_live_001.jsonl:evidence/analytics/m6_board_110x40_warehouse_story_v1_live_001"
  "board_110x40_warehouse_story_v1:evidence/sessions/m6_board_110x40_warehouse_story_v1_live_002.jsonl:evidence/analytics/m6_board_110x40_warehouse_story_v1_live_002"
)

CSV_FILES=(m6_zone_events.csv m6_zone_dwell.csv m6_zone_dwell_by_zone.csv m6_zone_transitions.csv)

echo "== M6 offline determinism verification =="

for c in "${CASES[@]}"; do
  IFS=":" read -r PROFILE JSONL LIVE_DIR <<<"$c"

  if [[ ! -f "$JSONL" ]]; then
    echo "[skip] missing JSONL: $JSONL"
    continue
  fi
  if [[ ! -d "$LIVE_DIR" ]]; then
    echo "[skip] missing live analytics dir: $LIVE_DIR"
    continue
  fi

  RUN_ID="$(date +%Y%m%d_%H%M%S)"
  OUT_DIR="evidence/analytics/_verify_offline_${RUN_ID}_$(basename "$LIVE_DIR")"
  mkdir -p "$OUT_DIR"

  echo
  echo "[case] profile=$PROFILE"
  echo "       jsonl=$JSONL"
  echo "       live=$LIVE_DIR"
  echo "       out =$OUT_DIR"

  python tools/zones_report_jsonl.py \
    "$JSONL" \
    --profile "$PROFILE" \
    --out "$OUT_DIR" \
    --prefix m6

  for f in "${CSV_FILES[@]}"; do
    echo "  diff: $f"
    diff -u "$LIVE_DIR/$f" "$OUT_DIR/$f"
  done

  echo "  -> OK (live == offline)"
done

echo
echo "ALL OK: offline determinism checks passed."
