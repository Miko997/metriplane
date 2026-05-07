#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---- user-tunable defaults (override via env) ----
METRIPLANE_VENV="${METRIPLANE_VENV:-$ROOT/.venv}"
RUNS="${RUNS:-~/metriplane-runs}"
CONFIG="${CONFIG:-configs/fusion_health_300fps.yaml}"

METRICS_HOST="${METRICS_HOST:-127.0.0.1}"
METRICS_PORT="${METRICS_PORT:-8000}"
METRICS_URL="http://${METRICS_HOST}:${METRICS_PORT}"
HEALTH_URL="${METRICS_URL}/health"

CUDA_ENV_SH="${CUDA_ENV_SH:-$ROOT/tools/env/vt_cuda13_env.sh}"

mkdir -p "$RUNS"

# ---- helpers ----
die() { echo "ERROR: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

activate_venv() {
  [ -d "$METRIPLANE_VENV" ] || die "METRIPLANE_VENV not found: $METRIPLANE_VENV (set METRIPLANE_VENV=/path/to/venv)"
  # shellcheck disable=SC1090
  source "$METRIPLANE_VENV/bin/activate"
}

free_ports() {
  # only kill host processes on these ports (safe; avoids “address already in use”)
  fuser -k 8765/tcp 8000/tcp 8001/tcp 2>/dev/null || true
}


maybe_source_cuda_env() {
  if [ -f "$CUDA_ENV_SH" ]; then
    # shellcheck disable=SC1090
    source "$CUDA_ENV_SH"
  fi
}

latest_run_dir() {
  local prefix="$1"
  ls -td "$RUNS"/"${prefix}"* 2>/dev/null | head -n 1 || true
}

pick_session() {
  # Priority:
  # 1) explicit arg
  # 2) last known good capture path
  # 3) demo dataset
  # 4) newest session.jsonl under RUNS
  local explicit="${1:-}"
  if [ -n "$explicit" ]; then
    echo "$explicit"; return 0
  fi
  if [ -f "$RUNS/m9_6_equiv_capture_001/session.jsonl" ]; then
    echo "$RUNS/m9_6_equiv_capture_001/session.jsonl"; return 0
  fi
  if [ -f "$ROOT/datasets/demo/session_001.jsonl" ]; then
    echo "$ROOT/datasets/demo/session_001.jsonl"; return 0
  fi
  local newest
  newest="$(ls -td "$RUNS"/*/session.jsonl 2>/dev/null | head -n 1 || true)"
  [ -n "$newest" ] || die "No session.jsonl found. Provide one: ./tools/m9.sh m9.1 /path/to/session.jsonl"
  echo "$newest"
}

health_compact() {
  curl -fsS "$HEALTH_URL" 2>/dev/null | python -c '
import sys, json
try:
  d = json.load(sys.stdin)
  overall = d.get("overall")
  comps = d.get("components", {}) or {}
  cam0 = (comps.get("camera.cam0") or {}).get("status")
  cam1 = (comps.get("camera.cam1") or {}).get("status")
  ws   = (comps.get("ws.send") or {}).get("status")
  print(f"overall={overall} cam0={cam0} cam1={cam1} ws={ws}")
except Exception:
  print("(health not ready)")
' || true
}


cmd_preflight() {
  activate_venv
  cd "$ROOT"

  echo "=== preflight ==="
  echo "repo: $ROOT"
  git rev-parse --short HEAD || true
  python --version || true
  python -c "import importlib.metadata as m; print('metriplane', m.version('metriplane'))" || true
  nvidia-smi -L || true
  ls -l /dev/v4l/by-id || true
  echo "RUNS=$RUNS"
  echo "CONFIG=$CONFIG"
}

cmd_m9_1() {
  activate_venv
  cd "$ROOT"

  local session
  session="$(pick_session "${1:-}")"
  [ -f "$session" ] || die "session not found: $session"

  echo "=== M9.1 determinism ==="
  echo "session=$session"
  rm -f /tmp/out1.jsonl /tmp/out2.jsonl /tmp/replay_determinism_001.csv

  metriplane replay --input "$session" --clock fixed --dt-ms 50 --run-id det_demo_001 --output-file /tmp/out1.jsonl
  metriplane replay --input "$session" --clock fixed --dt-ms 50 --run-id det_demo_001 --output-file /tmp/out2.jsonl

  python benchmarks/run_replay_determinism.py \
    --a /tmp/out1.jsonl --b /tmp/out2.jsonl \
    --out /tmp/replay_determinism_001.csv \
    --max-pos-diff-cm 0.0

  cat /tmp/replay_determinism_001.csv

  mkdir -p evidence/experiments
  cp /tmp/replay_determinism_001.csv evidence/experiments/replay_determinism_001.csv
  sha256sum evidence/experiments/replay_determinism_001.csv | tee evidence/experiments/replay_determinism_001.sha256
}

cmd_m9_2() {
  activate_venv
  cd "$ROOT"
  fuser -k 8001/tcp 2>/dev/null || true

  echo "=== M9.2 backpressure (auto metrics snapshots) ==="
  rm -f /tmp/backpressure_001.csv /tmp/backpressure_timeseries_001.csv

  python benchmarks/run_backpressure.py \
    --duration-s 30 \
    --input-hz 120 \
    --detect-ms 30 \
    --queue-max 5 \
    --policy KEEP_LATEST \
    --metrics-port 8001 \
    --out /tmp/backpressure_001.csv \
    --out-timeseries /tmp/backpressure_timeseries_001.csv &
  local pid=$!

  # give metrics time to come up
  sleep 1
  echo "--- metrics snapshot #1 ---"
  curl -fsS http://127.0.0.1:8001/metrics \
    | egrep "metriplane_queue_depth|metriplane_queue_dropped_total|metriplane_stage_latency_ms" \
    | head -n 80 || true

  sleep 8
  echo "--- metrics snapshot #2 ---"
  curl -fsS http://127.0.0.1:8001/metrics \
    | egrep "metriplane_queue_depth|metriplane_queue_dropped_total|metriplane_stage_latency_ms" \
    | head -n 80 || true

  wait $pid

  echo "--- summary CSV ---"
  cat /tmp/backpressure_001.csv

  mkdir -p evidence/experiments
  cp /tmp/backpressure_001.csv evidence/experiments/backpressure_001.csv
  cp /tmp/backpressure_timeseries_001.csv evidence/experiments/backpressure_timeseries_001.csv
  sha256sum evidence/experiments/backpressure_001.csv evidence/experiments/backpressure_timeseries_001.csv \
    | tee evidence/experiments/backpressure_001.sha256
}

cmd_m9_3() {
  activate_venv
  cd "$ROOT"
  free_ports

  echo "=== M9.3 health + degradation (cam1 fault) ==="
  echo "This will poll /health while the run is active."
  echo "health url: $HEALTH_URL"

  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "m9_3_health_demo_001" \
    --fault cam1_disconnect_after_s=8 \
    --duration-s 20 &
  local pid=$!

  # Poll compact health for ~20s
  for _ in $(seq 1 25); do
    echo -n "[health] "
    health_compact
    sleep 1
  done

  wait $pid || true

  local run_dir
  run_dir="$(latest_run_dir m9_3_health_demo_001)"
  echo "RUN_DIR=$run_dir"
  [ -n "$run_dir" ] && ls -lah "$run_dir" | egrep 'session.jsonl|meta.json|env.txt|health|checksums' || true
}

cmd_m9_4() {
  activate_venv
  cd "$ROOT"
  free_ports

  echo "=== M9.4 provenance (meta.json + run header) ==="
  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "m9_4_provenance_demo_001" \
    --duration-s 10

  local run_dir
  run_dir="$(latest_run_dir m9_4_provenance_demo_001)"
  echo "RUN_DIR=$run_dir"
  ls -lah "$run_dir"

  echo "=== meta.json (top) ==="
  sed -n '1,120p' "$run_dir/meta.json"

  echo "=== session header (first 2 lines) ==="
  head -n 2 "$run_dir/session.jsonl"

  mkdir -p evidence/experiments
  cp "$run_dir/meta.json" evidence/experiments/m9_4_meta.json
  sha256sum evidence/experiments/m9_4_meta.json | tee evidence/experiments/m9_4_meta.sha256
}

cmd_m9_5() {
  activate_venv
  cd "$ROOT"
  free_ports

  echo "=== M9.5 latency breakdown (METRIPLANE_TIMING) ==="
  METRIPLANE_TIMING=1 METRIPLANE_TIMING_FLUSH_EVERY=250 python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "m9_5_latency_demo_bothcams_002" \
    --duration-s 15

  local run_dir
  run_dir="$(latest_run_dir m9_5_latency_demo_bothcams_002)"
  echo "RUN_DIR=$run_dir"
  ls -lah "$run_dir" | egrep 'session.jsonl|latency_' || true

  python - "$run_dir" <<'PY'
import csv, sys
from pathlib import Path
run_dir = Path(sys.argv[1])
rows = list(csv.DictReader((run_dir/"latency_summary.csv").open()))
rows = [r for r in rows if r.get("stage") != "sleep"]
rows.sort(key=lambda r: float(r["p95_ms"]), reverse=True)

print("Top compute stages by p95 (excluding sleep):")
for r in rows[:15]:
    print(
        f"{r['stage']:<18} "
        f"p95={float(r['p95_ms']):7.3f}  "
        f"mean={float(r['mean_ms']):7.3f}  "
        f"max={float(r['max_ms']):7.3f}  "
        f"n={int(r['count']):5d}"
    )
PY

  mkdir -p evidence/experiments
  cp "$run_dir/latency_summary.csv" evidence/experiments/m9_5_latency_summary.csv
  sha256sum evidence/experiments/m9_5_latency_summary.csv | tee evidence/experiments/m9_5_latency_summary.sha256
}

cmd_m9_6() {
  activate_venv
  cd "$ROOT"
  free_ports

  echo "=== M9.6 GPU compute backend ==="
  maybe_source_cuda_env
  nvidia-smi -L || true

  echo "--- CuPy smoke ---"
  GPU_OK=0
  if python - <<'PY'
ok = False
try:
  import cupy as cp
  print("cupy:", cp.__version__)
  print("deviceCount:", cp.cuda.runtime.getDeviceCount())
  with cp.cuda.Device(0):
    x = cp.ones((8,8), dtype=cp.float32)
    y = x @ x
    cp.cuda.Stream.null.synchronize()
  ok = True
except Exception as e:
  print("cupy smoke: FAILED:", e)
print("cupy smoke:", "OK" if ok else "FAILED")
raise SystemExit(0 if ok else 2)
PY
  then
    GPU_OK=0
  else
    GPU_OK=$?
  fi

  if [[ "$GPU_OK" -ne 0 ]]; then
    echo
    echo "[m9.6] WARN: GPU backend not usable on this machine (CuPy kernel execution failed)."
    echo "[m9.6]      Continuing with CPU-only artifacts so the demo still passes."
    echo
    python benchmarks/run_compute_backend_comparison.py \
      --backends cpu \
      --out-csv /tmp/compute_backend_comparison_cpu_only.csv
    echo "[m9.6] wrote /tmp/compute_backend_comparison_cpu_only.csv"
    return 0
  fi

  echo "--- capture session for equivalence (15s) ---"
  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "m9_6_equiv_capture_001" \
    --duration-s 15

  local run_dir
  run_dir="$(latest_run_dir m9_6_equiv_capture_001)"
  echo "RUN_DIR=$run_dir"
  ls -lah "$run_dir" | egrep 'session.jsonl|meta.json|env.txt' || true

  echo "--- equivalence (CPU vs GPU) ---"
  export METRIPLANE_COMPUTE_BACKEND=gpu
  export METRIPLANE_GPU_DEVICE=0

  python benchmarks/run_compute_equivalence.py \
    --session "$run_dir/session.jsonl" \
    --out-csv "$run_dir/compute_equivalence.csv"

  cat "$run_dir/compute_equivalence.csv"

  echo "--- backend comparison (synthetic) ---"
  python benchmarks/run_compute_backend_comparison.py \
    --backends cpu,gpu \
    --out-csv "$run_dir/compute_backend_comparison.csv"

  echo "--- plots ---"
  python tools/plot_compute_backend_comparison.py \
    --in-csv "$run_dir/compute_backend_comparison.csv" \
    --out-dir "$run_dir" \
    --prefix compute_backend_comparison || true

  # If plotter wrote pngs into CWD, move them next to the CSV.
  for f in compute_backend_comparison_*png; do
    [ -f "$f" ] && mv -f "$f" "$run_dir/"
  done

  ls -lah "$run_dir" | egrep 'compute_.*(csv|png)$' || true
}

cmd_run_fusion() {
  # usage: ./tools/m9.sh run-fusion cpu|gpu <duration_s> <run_id>
  local backend="${1:-cpu}"
  local dur="${2:-10}"
  local rid="${3:-quick_run}"

  activate_venv
  cd "$ROOT"
  free_ports

  if [ "$backend" = "gpu" ]; then
    maybe_source_cuda_env
    export METRIPLANE_COMPUTE_BACKEND=gpu
    export METRIPLANE_GPU_DEVICE="${METRIPLANE_GPU_DEVICE:-0}"
  else
    export METRIPLANE_COMPUTE_BACKEND=cpu
    unset METRIPLANE_GPU_DEVICE || true
  fi

  echo "=== run_fusion backend=$backend duration_s=$dur run_id=$rid ==="
  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "$rid" \
    --duration-s "$dur"

  local run_dir
  run_dir="$(latest_run_dir "$rid")"
  echo "RUN_DIR=$run_dir"
  [ -n "$run_dir" ] && head -n 2 "$run_dir/session.jsonl" || true
}

cmd_gpu_watch() {
  have watch || die "'watch' not found"
  nvidia-smi -L || true
  watch -n 0.5 nvidia-smi
}

usage() {
  cat <<EOF
Usage:
  ./tools/m9.sh preflight
  ./tools/m9.sh m9.1 [session.jsonl]
  ./tools/m9.sh m9.2
  ./tools/m9.sh m9.3
  ./tools/m9.sh m9.4
  ./tools/m9.sh m9.5
  ./tools/m9.sh m9.6
  ./tools/m9.sh run-fusion cpu|gpu <duration_s> <run_id>
  ./tools/m9.sh gpu-watch

Environment overrides:
  METRIPLANE_VENV=/path/to/venv
  RUNS=/path/to/runs
  CONFIG=configs/fusion_health_300fps.yaml
  METRICS_HOST=127.0.0.1
  METRICS_PORT=8000
  CUDA_ENV_SH=tools/env/vt_cuda13_env.sh
EOF
}

cmd="${1:-}"
shift || true

case "$cmd" in
  preflight) cmd_preflight ;;
  m9.1)      cmd_m9_1 "${1:-}" ;;
  m9.2)      cmd_m9_2 ;;
  m9.3)      cmd_m9_3 ;;
  m9.4)      cmd_m9_4 ;;
  m9.5)      cmd_m9_5 ;;
  m9.6)      cmd_m9_6 ;;
  run-fusion) cmd_run_fusion "${1:-cpu}" "${2:-10}" "${3:-quick_run}" ;;
  gpu-watch)  cmd_gpu_watch ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command: $cmd (run ./tools/m9.sh --help)" ;;
esac
