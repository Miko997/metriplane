#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

IN_CFG="${1:?usage: capture.sh <config.yaml>}"

DURATION_S="${DURATION_S:-45}"
POLL_S="${POLL_S:-1}"
CAM1_AFTER_S="${CAM1_AFTER_S:-8}"   # 0 disables
WS_AFTER_S="${WS_AFTER_S:-0}"       # 0 disables

STAMP="$(date +%Y%m%d_%H%M%S)"
OUTROOT="evidence/experiments/_demo3_health_dumps"
OUTDIR="${OUTROOT}/vt_demo3_health_${STAMP}"
mkdir -p "$OUTDIR"
TMP_CFG="$OUTDIR/config_tmp.yaml"

# ---- cleanup (best-effort) ----
pkill -f 'metriplane\.run_fusion' 2>/dev/null || true
if command -v lsof >/dev/null 2>&1; then
  lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill -9 || true
  lsof -tiTCP:8765 -sTCP:LISTEN | xargs -r kill -9 || true
fi

# ---- pick ports + write temp config ----
read -r METRICS_HOST METRICS_PORT WS_HOST WS_PORT < <(python - "$IN_CFG" "$TMP_CFG" <<'PY'
import socket, sys, yaml
from pathlib import Path

host = "127.0.0.1"
in_cfg = Path(sys.argv[1])
out_cfg = Path(sys.argv[2])

cfg = yaml.safe_load(in_cfg.read_text(encoding="utf-8"))

def port_free(p: int) -> bool:
    s = socket.socket()
    try:
        s.bind((host, p))
        return True
    except OSError:
        return False
    finally:
        s.close()

def pick(preferred: int) -> int:
    if preferred and port_free(preferred):
        return preferred
    s = socket.socket()
    s.bind((host, 0))
    p = s.getsockname()[1]
    s.close()
    return p

metrics_port = pick(8000)
ws_port = pick(8765)

cfg["metrics_host"] = host
cfg["metrics_port"] = int(metrics_port)
cfg["ws_host"] = host
cfg["ws_port"] = int(ws_port)

out_cfg.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
print(host, metrics_port, host, ws_port)
PY
)

METRICS_URL="http://${METRICS_HOST}:${METRICS_PORT}"
WS_URL="ws://${WS_HOST}:${WS_PORT}"

{
  echo "in_cfg=$IN_CFG"
  echo "tmp_cfg=$TMP_CFG"
  echo "date=$(date -Iseconds)"
  echo "pwd=$(pwd)"
  echo "python=$(python --version 2>&1)"
  echo "git=$(git rev-parse --short HEAD 2>/dev/null || true)"
  echo "metrics_url=$METRICS_URL"
  echo "ws_url=$WS_URL"
  echo "CAM1_AFTER_S=$CAM1_AFTER_S"
  echo "WS_AFTER_S=$WS_AFTER_S"
  echo "DURATION_S=$DURATION_S"
  echo "POLL_S=$POLL_S"
} > "$OUTDIR/meta.txt"

cp -a "$TMP_CFG" "$OUTDIR/config_used.yaml"

FAULT_ARGS=()
if [[ "${CAM1_AFTER_S}" != "0" ]]; then FAULT_ARGS+=(--fault "cam1_disconnect_after_s=${CAM1_AFTER_S}"); fi
if [[ "${WS_AFTER_S}" != "0" ]]; then FAULT_ARGS+=(--fault "ws_fail_after_s=${WS_AFTER_S}"); fi

RUN_CMD=(python -m metriplane.run_fusion --config "$TMP_CFG" "${FAULT_ARGS[@]}")
printf '%q ' "${RUN_CMD[@]}" > "$OUTDIR/run_cmd.txt"
echo >> "$OUTDIR/run_cmd.txt"

cleanup() {
  # Stop ws_drain first
  [[ -n "${WS_PID:-}" ]] && kill "${WS_PID}" 2>/dev/null || true
  # Ask Metriplane to stop more gently (SIGINT), then SIGTERM
  if [[ -n "${METRIPLANE_PID:-}" ]]; then
    kill -INT "${METRIPLANE_PID}" 2>/dev/null || true
    sleep 0.5
    kill "${METRIPLANE_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "OUTDIR=$OUTDIR"
echo "metrics: $METRICS_URL"
echo "ws:      $WS_URL"
echo "faults:  cam1_disconnect_after_s=${CAM1_AFTER_S}  ws_fail_after_s=${WS_AFTER_S}"
echo
echo "Terminal B helper:"
echo "  export METRICS_URL=\"$METRICS_URL\""
echo "  DURATION_S=25 bash tools/demos/003_health_degradation/watch_health_lines.sh"
echo

"${RUN_CMD[@]}" > "$OUTDIR/run.log" 2>&1 &
METRIPLANE_PID="$!"
echo "$METRIPLANE_PID" > "$OUTDIR/pid.txt"

echo "Waiting for $METRICS_URL/health ..."
for _ in $(seq 1 200); do
  if curl -fsS "$METRICS_URL/health" > "$OUTDIR/health_tmp.json" 2>/dev/null; then
    echo "OK: /health is up."
    break
  fi
  if ! kill -0 "$METRIPLANE_PID" 2>/dev/null; then
    echo "ERROR: run_fusion exited before /health came up."
    tail -n 120 "$OUTDIR/run.log" || true
    exit 1
  fi
  sleep 0.25
done

# Show WS proof LIVE in Terminal A and capture to file.
python "$SCRIPT_DIR/ws_drain.py" "$WS_URL" --every 50 2>&1 | tee "$OUTDIR/ws_client.log" &
WS_PID="$!"
echo "$WS_PID" > "$OUTDIR/ws_pid.txt"

echo "Sampling /health for ${DURATION_S}s ..."
T_END=$(( $(date +%s) + DURATION_S ))
: > "$OUTDIR/health.jsonl"

while [[ "$(date +%s)" -lt "$T_END" ]]; do
  TS="$(date -Iseconds)"
  if curl -fsS "$METRICS_URL/health" 2>/dev/null \
      | jq -c --arg ts "$TS" '. + {ts:$ts}' >> "$OUTDIR/health.jsonl"; then
    curl -fsS "$METRICS_URL/health" > "$OUTDIR/health_tmp.json" 2>/dev/null || true
  else
    echo "{\"ts\":\"$TS\",\"http\":0}" >> "$OUTDIR/health.jsonl"
  fi
  sleep "$POLL_S"
done

cp -a "$OUTDIR/health_tmp.json" "$OUTDIR/health_final.json" || true
curl -fsS "$METRICS_URL/metrics" > "$OUTDIR/metrics_full.txt" 2>/dev/null || true

# Checksums (do it inside OUTDIR so relative paths exist)
(
  cd "$OUTDIR"
  sha256sum \
    meta.txt run_cmd.txt config_used.yaml health_final.json health.jsonl metrics_full.txt ws_client.log \
    > checksums.sha256
)

echo
echo "DONE: $OUTDIR"
echo "Quick proof:"
echo "  python tools/demos/003_health_degradation/health_transitions.py \"$OUTDIR/health.jsonl\""
echo "  jq '.overall, .components[\"camera.cam0\"], .components[\"camera.cam1\"], .components[\"ws.send\"]' \"$OUTDIR/health_final.json\""
echo "  tail -n 5 \"$OUTDIR/checksums.sha256\""
