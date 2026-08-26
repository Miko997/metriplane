#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail

if [[ -z "${RUNS_DIR:-}" ]]; then
  RUNS_DIR="$(python -c '
import sys
from metriplane.paths import PlatformPathError, resolve_platform_paths

try:
    print(resolve_platform_paths().runs_dir)
except PlatformPathError as exc:
    print(f"platform path error: {exc}", file=sys.stderr)
    raise SystemExit(2)
')"
fi
CFG="${CFG:-configs/fusion_health.yaml}"

RUN_ID="${RUN_ID:-sd4_test_001}"
REPLAY_RUN_ID="${REPLAY_RUN_ID:-sd4_replay_001}"

FUSION_METRICS_PORT="${FUSION_METRICS_PORT:-8000}"
FUSION_WS_PORT="${FUSION_WS_PORT:-8765}"

REPLAY_METRICS_PORT="${REPLAY_METRICS_PORT:-8001}"
REPLAY_WS_PORT="${REPLAY_WS_PORT:-8766}"

echo "=== SD4 Demo (M9.4 provenance) ==="
echo "RUNS_DIR=$RUNS_DIR"
echo "CFG=$CFG"
echo "RUN_ID=$RUN_ID"
echo "REPLAY_RUN_ID=$REPLAY_RUN_ID"
echo

# -------------------------
# Guard A: refuse if ports in use
# -------------------------
if ss -ltnp | grep -Eq ":(8000|8765)\s"; then
  echo "ERROR: ports 8000/8765 already in use. Stop the existing fusion first." >&2
  ss -ltnp | egrep ":(8000|8765)\s" >&2 || true
  exit 2
fi

# Clean old folders to avoid -1 suffix surprises
rm -rf "$RUNS_DIR/$RUN_ID" || true
rm -rf "$RUNS_DIR/${REPLAY_RUN_ID}"* || true

mkdir -p "$RUNS_DIR"

cleanup_pid() {
  local pid="${1:-}"
  if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill -INT "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
}

# -------------------------
# 1) Run fusion briefly to generate run folder artifacts
# -------------------------
echo "==> 1) Running fusion for ~5s to generate run folder..."
python -m metriplane.run_fusion --config "$CFG" --runs-dir "$RUNS_DIR" --run-id "$RUN_ID" &
PID=$!

# Guard B: fail if process dies early (port conflict, import error, etc.)
for _ in {1..50}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "ERROR: run_fusion exited early. See traceback above." >&2
    wait "$PID" || true
    exit 1
  fi
  # optional: break once ports are listening
  if ss -ltnp | grep -Eq ":(8000|8765)\s"; then
    break
  fi
  sleep 0.1
done

sleep 5
cleanup_pid "$PID"

RUN_DIR="$RUNS_DIR/$RUN_ID"
echo
echo "==> Run dir created: $RUN_DIR"
ls -lah "$RUN_DIR"
echo

# -------------------------
# 2) Verify config hash matches meta.json
# -------------------------
echo "==> 2) Verify config hash matches meta.json"
RUN_DIR="$RUN_DIR" python - <<'PY'
import hashlib, json, os
from pathlib import Path
run_dir = Path(os.environ["RUN_DIR"])
canon = run_dir.joinpath("config.canonical.json").read_bytes()
meta  = json.loads(run_dir.joinpath("meta.json").read_text())
h = hashlib.sha256(canon).hexdigest()
print("sha256(config.canonical.json) =", h)
print("meta config.hash             =", meta["config"]["hash"])
print("MATCH =", h == meta["config"]["hash"])
PY
echo

# -------------------------
# 3) Show JSONL header + first frame provenance
# -------------------------
echo "==> 3) JSONL header (first line):"
head -n 1 "$RUN_DIR/session.jsonl" | jq .
echo
echo "==> First frame provenance (second line):"
sed -n '2p' "$RUN_DIR/session.jsonl" | jq '{run_id,config_hash,git_commit,frame_id,ts,source_backend}'
echo

# -------------------------
# 4) Create replay config that replays from the run folder
# -------------------------
echo "==> 4) Writing replay config: $RUN_DIR/config.replay.yaml"
python - <<PY
import yaml
from pathlib import Path

run_dir = Path("$RUN_DIR")
cfg = yaml.safe_load((run_dir/"config.yaml").read_text()) or {}

cfg["source_mode"]  = "replay"
cfg["replay_input"] = str(run_dir/"session.jsonl")
cfg["replay_loop"]  = True
cfg["replay_speed"] = 1.0

# avoid conflicts with default ports
cfg["metrics_port"] = int("$REPLAY_METRICS_PORT")
cfg["ws_port"]      = int("$REPLAY_WS_PORT")

# IMPORTANT: don't overwrite any mirror file during replay demo
cfg["record_jsonl"] = None

out = run_dir/"config.replay.yaml"
out.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
print("wrote", out)
PY
echo

# -------------------------
# 5) Run replay and prove /health is OK
# -------------------------
echo "==> 5) Running replay briefly and curling /health..."
python -m metriplane.run --config "$RUN_DIR/config.replay.yaml" --runs-dir "$RUNS_DIR" --run-id "$REPLAY_RUN_ID" &
RPID=$!

sleep 1
ss -ltnp | egrep ":(${REPLAY_METRICS_PORT}|${REPLAY_WS_PORT})\s" || echo "WARNING: expected replay ports not listening (yet?)"
curl -fsS "http://127.0.0.1:${REPLAY_METRICS_PORT}/health" | jq '.overall, .components.camera.details'

cleanup_pid "$RPID"

echo
echo "==> Replay run folders created:"
ls -dt "$RUNS_DIR/${REPLAY_RUN_ID}"* | head -n 5

echo
echo "=== SD4 demo complete ==="
