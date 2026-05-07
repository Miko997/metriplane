#!/usr/bin/env bash
set -euo pipefail

: "${METRICS_URL:?Set METRICS_URL like http://127.0.0.1:8000}"

DURATION_S="${DURATION_S:-25}"
POLL_S="${POLL_S:-1}"

t_end=$(( $(date +%s) + DURATION_S ))

while [[ "$(date +%s)" -lt "$t_end" ]]; do
  ts="$(date -Iseconds)"
  json="$(curl -fsS "$METRICS_URL/health" 2>/dev/null || true)"

  if [[ -n "$json" ]]; then
    overall="$(jq -r '.overall' <<<"$json")"
    cam0="$(jq -r '.components["camera.cam0"].status // "n/a"' <<<"$json")"
    cam1="$(jq -r '.components["camera.cam1"].status // "n/a"' <<<"$json")"
    wssend="$(jq -r '.components["ws.send"].status // "n/a"' <<<"$json")"
    printf "%s overall=%s cam0=%s cam1=%s ws.send=%s\n" "$ts" "$overall" "$cam0" "$cam1" "$wssend"
  else
    printf "%s health_http=0\n" "$ts"
  fi

  sleep "$POLL_S"
done
