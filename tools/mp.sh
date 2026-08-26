#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail

export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# Find repository root (walk upward until we find pyproject.toml AND benchmarks/)
find_repo_root() {
  local dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/pyproject.toml" ] && [ -d "$dir/benchmarks" ]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  echo "ERROR: Could not find repository root (pyproject.toml + benchmarks/)" >&2
  exit 1
}

ROOT="${METRIPLANE_REPO_ROOT:-$(find_repo_root)}"

# ---- defaults (override via env) ----
METRIPLANE_VENV="${METRIPLANE_VENV:-$ROOT/.venv}"
CONFIG="${CONFIG:-configs/fusion_health_300fps.yaml}"
CUDA_ENV_SH="${CUDA_ENV_SH:-$ROOT/tools/env/vt_cuda13_env.sh}"

if [[ -z "${RUNS:-}" ]]; then
  PATHS_PYTHON="python3"
  if [[ -x "$METRIPLANE_VENV/bin/python" ]]; then
    PATHS_PYTHON="$METRIPLANE_VENV/bin/python"
  elif [[ -x "$METRIPLANE_VENV/Scripts/python.exe" ]]; then
    PATHS_PYTHON="$METRIPLANE_VENV/Scripts/python.exe"
  fi
  RUNS="$(cd "$ROOT" && "$PATHS_PYTHON" -c '
import sys
from metriplane.paths import PlatformPathError, resolve_platform_paths

try:
    print(resolve_platform_paths().runs_dir)
except PlatformPathError as exc:
    print(f"platform path error: {exc}", file=sys.stderr)
    raise SystemExit(2)
')"
fi

METRICS_HOST="${METRICS_HOST:-127.0.0.1}"
METRICS_PORT="${METRICS_PORT:-8000}"
METRICS_URL="http://${METRICS_HOST}:${METRICS_PORT}"
HEALTH_URL="${METRICS_URL}/health"

mkdir -p "$RUNS"

die(){ echo "ERROR: $*" >&2; exit 1; }

use_canonical_evidence_out() {
  case "${METRIPLANE_EVIDENCE_OUT:-0}" in
    1|true|TRUE|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

experiment_out_dir() {
  local outdir
  if use_canonical_evidence_out; then
    outdir="evidence/experiments"
  else
    outdir="$RUNS/demo-evidence"
  fi
  mkdir -p "$outdir"
  echo "$outdir"
}

activate() {
  [ -d "$METRIPLANE_VENV" ] || die "METRIPLANE_VENV not found: $METRIPLANE_VENV  (set METRIPLANE_VENV=/path/to/venv)"
  if [ -f "$METRIPLANE_VENV/bin/activate" ]; then
    # shellcheck disable=SC1090
    source "$METRIPLANE_VENV/bin/activate"
  elif [ -f "$METRIPLANE_VENV/Scripts/activate" ]; then
    # shellcheck disable=SC1090
    source "$METRIPLANE_VENV/Scripts/activate"
  else
    echo "No virtualenv activation script found under $METRIPLANE_VENV"
    exit 1
  fi
}

free_ports() {
  # only kill host processes on these ports (safe; avoids “address already in use”)
  fuser -k 8765/tcp 8000/tcp 8001/tcp 2>/dev/null || true
}


maybe_cuda_env() {
  if [ -f "$CUDA_ENV_SH" ]; then
    # shellcheck disable=SC1090
    source "$CUDA_ENV_SH"
  fi
}

latest_run_dir() {
  local prefix="$1"
  ls -td "$RUNS"/"${prefix}"* 2>/dev/null | head -n 1 || true
}

session_has_frames() {
  local session="$1"
  python - "$session" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(1)

header_types = {"header", "run_header", "provenance"}
try:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if (rec.get("type") or rec.get("record_type")) in header_types:
                continue
            if "ts" in rec or "ts_ns" in rec:
                raise SystemExit(0)
except OSError:
    raise SystemExit(1)
raise SystemExit(1)
PY
}

pick_session() {
  # priority:
  # 1) explicit arg
  # 2) newest session.jsonl under RUNS that contains at least one frame
  # 3) demo dataset if exists
  local explicit="${1:-}"
  if [ -n "$explicit" ]; then
    session_has_frames "$explicit" || die "session has no replay frames: $explicit"
    echo "$explicit"
    return 0
  fi
  local newest=""
  while IFS= read -r newest; do
    [ -n "$newest" ] || continue
    if session_has_frames "$newest"; then
      echo "$newest"
      return 0
    fi
  done < <(ls -t "$RUNS"/*/session.jsonl 2>/dev/null || true)
  if [ -f "$ROOT/datasets/demo/session_001.jsonl" ]; then
    session_has_frames "$ROOT/datasets/demo/session_001.jsonl" || die "demo session has no replay frames: $ROOT/datasets/demo/session_001.jsonl"
    echo "$ROOT/datasets/demo/session_001.jsonl"
    return 0
  fi
  die "No session.jsonl found. Pass one: ./tools/mp.sh deterministic-replay /path/to/session.jsonl"
}

health_compact() {
  python - "$HEALTH_URL" <<'PY' || true
import json
import sys
from urllib.request import urlopen

try:
  with urlopen(sys.argv[1], timeout=2.0) as response:
    d = json.load(response)
  overall = d.get("overall")
  comps = d.get("components", {}) or {}
  cam0 = (comps.get("camera.cam0") or {}).get("status")
  cam1 = (comps.get("camera.cam1") or {}).get("status")
  ws   = (comps.get("ws.send") or {}).get("status")
  print(f"overall={overall} cam0={cam0} cam1={cam1} ws={ws}")
except Exception:
  print("(health not ready)")
PY
}

cmd_preflight() {
  activate
  cd "$ROOT"
  echo "=== preflight ==="
  echo "repo: $ROOT"
  git rev-parse --short HEAD || true
  python --version || true
  python -c "import importlib.metadata as m; print('metriplane', m.version('metriplane'))" || true
  nvidia-smi -L || true
  ls -l /dev/v4l/by-id || true
  echo "RUNS=$RUNS"
  echo "METRIPLANE_EVIDENCE_OUT=${METRIPLANE_EVIDENCE_OUT:-0}"
  echo "CONFIG=$CONFIG"
}

cmd_run_fusion() {
  # usage: ./tools/mp.sh run-fusion cpu|gpu <duration_s> <run_id>
  local backend="${1:-cpu}"
  local dur="${2:-10}"
  local rid="${3:-run_fusion_001}"

  activate
  cd "$ROOT"

  if [ "$backend" = "gpu" ]; then
    maybe_cuda_env
    export METRIPLANE_COMPUTE_BACKEND=gpu
    export METRIPLANE_GPU_DEVICE="${METRIPLANE_GPU_DEVICE:-0}"
  else
    export METRIPLANE_COMPUTE_BACKEND=cpu
    unset METRIPLANE_GPU_DEVICE || true
  fi

  echo "=== fusion run (backend=$backend, duration_s=$dur, run_id=$rid) ==="
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

cmd_deterministic_replay() {
  # usage: ./tools/mp.sh deterministic-replay [session.jsonl]
  activate
  cd "$ROOT"

  local session
  session="$(pick_session "${1:-}")"
  [ -f "$session" ] || die "session not found: $session"

  echo "=== deterministic replay (fixed-step) ==="
  echo "session=$session"
  rm -f /tmp/out1.jsonl /tmp/out2.jsonl /tmp/replay_determinism.csv

  metriplane replay --input "$session" --clock fixed --dt-ms 50 --run-id det_replay --output-file /tmp/out1.jsonl
  metriplane replay --input "$session" --clock fixed --dt-ms 50 --run-id det_replay --output-file /tmp/out2.jsonl

  python benchmarks/run_replay_determinism.py \
    --a /tmp/out1.jsonl --b /tmp/out2.jsonl \
    --out /tmp/replay_determinism.csv \
    --max-pos-diff-cm 0.0

  cat /tmp/replay_determinism.csv

  local outdir
  outdir="$(experiment_out_dir)"
  cp /tmp/replay_determinism.csv "$outdir/replay_determinism.csv"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$outdir/replay_determinism.csv" | tee "$outdir/replay_determinism.sha256"
  else
    shasum -a 256 "$outdir/replay_determinism.csv" | tee "$outdir/replay_determinism.sha256"
  fi
  echo "OUTDIR=$outdir"
}

cmd_backpressure() {
  # usage: ./tools/mp.sh backpressure
  activate
  cd "$ROOT"

  echo "=== bounded queues / backpressure benchmark ==="
  rm -f /tmp/backpressure_summary.csv /tmp/backpressure_timeseries.csv

  python benchmarks/run_backpressure.py \
    --duration-s 30 \
    --input-hz 120 \
    --detect-ms 30 \
    --queue-max 5 \
    --policy KEEP_LATEST \
    --metrics-port 8001 \
    --out /tmp/backpressure_summary.csv \
    --out-timeseries /tmp/backpressure_timeseries.csv &
  local pid=$!

  sleep 1
  echo "--- metrics snapshot (while running) ---"
  curl -fsS http://127.0.0.1:8001/metrics \
    | egrep "metriplane_queue_depth|metriplane_queue_dropped_total|metriplane_stage_latency_ms" \
    | head -n 80 || true

  wait $pid
  echo "--- summary ---"
  cat /tmp/backpressure_summary.csv

  local outdir
  outdir="$(experiment_out_dir)"
  cp /tmp/backpressure_summary.csv "$outdir/backpressure_summary.csv"
  cp /tmp/backpressure_timeseries.csv "$outdir/backpressure_timeseries.csv"
  sha256sum "$outdir/backpressure_summary.csv" "$outdir/backpressure_timeseries.csv" \
    | tee "$outdir/backpressure.sha256"
  echo "OUTDIR=$outdir"
}

cmd_health_degrade_cam1() {
  # usage: ./tools/mp.sh health-degrade-cam1
  activate
  cd "$ROOT"

  echo "=== health + graceful degradation (cam1 disconnect injected) ==="
  echo "health url: $HEALTH_URL"

  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "health_degrade_cam1_001" \
    --fault cam1_disconnect_after_s=8 \
    --duration-s 20 &
  local pid=$!

  for _ in $(seq 1 25); do
    echo -n "[health] "
    health_compact
    sleep 1
  done

  wait $pid || true

  local run_dir
  run_dir="$(latest_run_dir health_degrade_cam1_001)"
  echo "RUN_DIR=$run_dir"
  [ -n "$run_dir" ] && ls -lah "$run_dir" | egrep 'session.jsonl|meta.json|env.txt|health|checksums' || true
}

cmd_provenance() {
  # usage: ./tools/mp.sh provenance
  activate
  cd "$ROOT"

  echo "=== run provenance (camera-free meta.json + run header) ==="
  python - "$RUNS" "$ROOT/datasets/demo/session_001.jsonl" <<'PY'
import json
import sys
from pathlib import Path

from metriplane.config import Config
from metriplane.provenance.run_provenance import create_run_context, is_header_record, open_jsonl_writer

runs_dir = Path(sys.argv[1])
source_session = Path(sys.argv[2])
if not source_session.is_file():
    raise SystemExit(f"demo session not found: {source_session}")

cfg = Config(
    source_mode="replay",
    replay_input=str(source_session),
    replay_loop=False,
    profile="camera_free_demo",
    target_fps=30,
    runs_dir=str(runs_dir),
)
ctx = create_run_context(
    cfg,
    config_path=Path("datasets/demo/session_001.jsonl"),
    argv=["./tools/mp.sh", "provenance"],
    run_id="provenance_run_001",
    runs_dir=str(runs_dir),
)

writer = open_jsonl_writer(primary_path=ctx.session_jsonl, mirror_path=None)
writer.write(ctx.header_record())

frames = 0
with source_session.open("r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if not isinstance(rec, dict) or is_header_record(rec):
            continue
        rec = dict(rec)
        rec["run_id"] = ctx.run_id
        rec["config_hash"] = ctx.config_hash
        rec["git_commit"] = ctx.git.commit
        rec.setdefault("schema_version", "1.0")
        writer.write(rec)
        frames += 1
        if frames >= 5:
            break

writer.close()
if frames == 0:
    raise SystemExit(f"demo session has no replay frames: {source_session}")

print(f"camera_free=true")
print(f"source_session={source_session}")
print(f"frames_written={frames}")
print(f"run_dir={ctx.run_dir}")
PY

  local run_dir
  run_dir="$(latest_run_dir provenance_run_001)"
  echo "RUN_DIR=$run_dir"
  ls -lah "$run_dir"

  echo "=== meta.json (top) ==="
  sed -n '1,120p' "$run_dir/meta.json"

  echo "=== session.jsonl header (first 2 lines) ==="
  head -n 2 "$run_dir/session.jsonl"

  local outdir
  outdir="$(experiment_out_dir)"
  cp "$run_dir/meta.json" "$outdir/run_meta.json"
  sha256sum "$outdir/run_meta.json" | tee "$outdir/run_meta.sha256"
  echo "OUTDIR=$outdir"
}

cmd_timing_breakdown() {
  # usage: ./tools/mp.sh timing-breakdown
  activate
  cd "$ROOT"

  echo "=== per-stage latency breakdown (METRIPLANE_TIMING) ==="
  METRIPLANE_TIMING=1 METRIPLANE_TIMING_FLUSH_EVERY=250 python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "timing_breakdown_001" \
    --duration-s 15

  local run_dir
  run_dir="$(latest_run_dir timing_breakdown_001)"
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

  local outdir
  outdir="$(experiment_out_dir)"
  cp "$run_dir/latency_summary.csv" "$outdir/latency_summary.csv"
  sha256sum "$outdir/latency_summary.csv" | tee "$outdir/latency_summary.sha256"
  echo "OUTDIR=$outdir"
}

cmd_gpu_smoke() {
  activate
  cd "$ROOT"
  maybe_cuda_env

  echo "=== GPU + CuPy smoke ==="
  nvidia-smi -L || true
  python - <<'PY'
ok=False
try:
  import cupy as cp
  print("cupy:", cp.__version__)
  print("deviceCount:", cp.cuda.runtime.getDeviceCount())
  with cp.cuda.Device(0):
    x = cp.ones((512,512), dtype=cp.float32)
    y = x @ x
    cp.cuda.Stream.null.synchronize()
  ok=True
except Exception as e:
  print("CuPy FAILED:", e)
print("CuPy smoke:", "OK" if ok else "FAILED")
PY
}

cmd_gpu_equivalence() {
  # usage: ./tools/mp.sh gpu-equivalence [session.jsonl]
  activate
  cd "$ROOT"
  maybe_cuda_env

  local session
  session="$(pick_session "${1:-}")"
  [ -f "$session" ] || die "session not found: $session"

  echo "=== GPU equivalence (CPU vs GPU) ==="
  export METRIPLANE_COMPUTE_BACKEND=gpu
  export METRIPLANE_GPU_DEVICE="${METRIPLANE_GPU_DEVICE:-0}"

  local outdir="$RUNS/gpu_equivalence_001"
  mkdir -p "$outdir"

  python benchmarks/run_compute_equivalence.py \
    --session "$session" \
    --out-csv "$outdir/compute_equivalence.csv"

  cat "$outdir/compute_equivalence.csv"
  sha256sum "$outdir/compute_equivalence.csv" | tee "$outdir/compute_equivalence.sha256"
  echo "OUTDIR=$outdir"
}

cmd_gpu_benchmark() {
  activate
  cd "$ROOT"
  maybe_cuda_env

  echo "=== CPU vs GPU backend benchmark (synthetic) ==="
  export METRIPLANE_COMPUTE_BACKEND=gpu
  export METRIPLANE_GPU_DEVICE="${METRIPLANE_GPU_DEVICE:-0}"

  local outdir="$RUNS/gpu_benchmark_001"
  mkdir -p "$outdir"

  python benchmarks/run_compute_backend_comparison.py \
    --backends cpu,gpu \
    --out-csv "$outdir/compute_backend_comparison.csv"

  # plotter may write pngs into CWD; we move them into outdir
  python tools/plot_compute_backend_comparison.py --in-csv "$outdir/compute_backend_comparison.csv" --out-dir "$outdir" || true
  for f in compute_backend_comparison_*png; do
    [ -f "$f" ] && mv -f "$f" "$outdir/"
  done

  ls -lah "$outdir" | egrep 'compute_.*(csv|png)$' || true
  sha256sum "$outdir"/compute_* 2>/dev/null | tee "$outdir/checksums.sha256" || true
  echo "OUTDIR=$outdir"
}

cmd_gpu_watch() {
  command -v watch >/dev/null 2>&1 || die "'watch' not installed"
  nvidia-smi -L || true
  watch -n 0.5 nvidia-smi
}

usage() {
  cat <<EOF
Usage (feature names only):
  ./tools/mp.sh preflight
  ./tools/mp.sh run-fusion cpu|gpu <duration_s> <run_id>

  ./tools/mp.sh deterministic-replay [session.jsonl]
  ./tools/mp.sh backpressure
  ./tools/mp.sh health-degrade-cam1
  ./tools/mp.sh provenance
  ./tools/mp.sh timing-breakdown

  ./tools/mp.sh gpu-smoke
  ./tools/mp.sh gpu-equivalence [session.jsonl]
  ./tools/mp.sh gpu-benchmark
  ./tools/mp.sh gpu-watch

Env overrides:
  METRIPLANE_VENV=/path/to/venv
  RUNS=/path/to/metriplane-runs
  METRIPLANE_EVIDENCE_OUT=1  # write canonical artifacts to evidence/experiments
  CONFIG=configs/fusion_health_300fps.yaml
  CUDA_ENV_SH=tools/env/vt_cuda13_env.sh
  METRICS_HOST=127.0.0.1  METRICS_PORT=8000

Demo artifacts default to RUNS/demo-evidence unless METRIPLANE_EVIDENCE_OUT=1.
EOF
}

cmd_health_degrade_cam1_v2() {
  activate
  cd "$ROOT"

  echo "=== graceful degradation (cam1 disconnect injected) ==="
  local rid="health_degrade_cam1_001"

  python -m metriplane.run_fusion \
    --config "$CONFIG" \
    --runs-dir "$RUNS" \
    --run-id "$rid" \
    --fault cam1_disconnect_after_s=8 \
    --duration-s 20

  local run_dir
  run_dir="$(ls -td "$RUNS"/"${rid}"* 2>/dev/null | head -n 1 || true)"
  if [ -z "${run_dir:-}" ]; then
    echo "ERROR: could not find run dir under RUNS=$RUNS for rid=$rid"
    return 0
  fi

  echo "RUN_DIR=$run_dir"
  ls -lah "$run_dir" | egrep 'meta.json|session.jsonl|env.txt' || true

  echo "=== health summary from session.jsonl (no HTTP required) ==="
  python tools/session_health_summary.py "$run_dir/session.jsonl" || true

  local outdir
  outdir="$(experiment_out_dir)"
  cp "$run_dir/meta.json" "$outdir/health_degrade_cam1_meta.json"
  sha256sum "$outdir/health_degrade_cam1_meta.json" | tee "$outdir/health_degrade_cam1_meta.sha256"
  echo "OUTDIR=$outdir"
}

cmd_demo_all() {
  local dur_s="${1:-10}"

  echo "=== demo-all (feature showcase) ==="
  cmd_preflight

  local cpu_prefix="demo_fusion_cpu"
  local gpu_prefix="demo_fusion_gpu"

  echo "--- fusion (CPU) ---"
  cmd_run_fusion cpu "$dur_s" "$cpu_prefix"
  local cpu_dir
  cpu_dir="$(ls -td "$RUNS"/"${cpu_prefix}"* 2>/dev/null | head -n 1 || true)"
  if [ -z "${cpu_dir:-}" ]; then
    echo "ERROR: could not locate CPU run dir for prefix=$cpu_prefix"
    return 1
  fi

  echo "--- deterministic replay (CPU run) ---"
  cmd_deterministic_replay "$cpu_dir/session.jsonl"

  echo "--- bounded queues / backpressure ---"
  cmd_backpressure

  echo "--- graceful degradation (cam1 disconnect) ---"
  cmd_health_degrade_cam1_v2

  echo "--- provenance ---"
  cmd_provenance

  echo "--- per-stage timing ---"
  cmd_timing_breakdown

  echo "--- GPU smoke + equivalence + benchmark ---"
  cmd_gpu_smoke
  cmd_gpu_equivalence "$cpu_dir/session.jsonl"
  cmd_gpu_benchmark

  echo "--- fusion (GPU) ---"
  cmd_run_fusion gpu "$dur_s" "$gpu_prefix"
  local gpu_dir
  gpu_dir="$(ls -td "$RUNS"/"${gpu_prefix}"* 2>/dev/null | head -n 1 || true)"
  if [ -z "${gpu_dir:-}" ]; then
    echo "ERROR: could not locate GPU run dir for prefix=$gpu_prefix"
    return 1
  fi

  echo "--- deterministic replay (GPU run) ---"
  cmd_deterministic_replay "$gpu_dir/session.jsonl"

  echo "=== demo-all DONE ==="
  echo "Runs dir: $RUNS"
}

cmd="${1:-}"; shift || true
case "$cmd" in
  demo-all) cmd_demo_all "${1:-10}" ;;
  preflight) cmd_preflight ;;
  run-fusion) cmd_run_fusion "${1:-cpu}" "${2:-10}" "${3:-run_fusion_001}" ;;
  deterministic-replay) cmd_deterministic_replay "${1:-}" ;;
  backpressure) cmd_backpressure ;;
  health-degrade-cam1) cmd_health_degrade_cam1_v2 ;;
  provenance) cmd_provenance ;;
  timing-breakdown) cmd_timing_breakdown ;;
  gpu-smoke) cmd_gpu_smoke ;;
  gpu-equivalence) cmd_gpu_equivalence "${1:-}" ;;
  gpu-benchmark) cmd_gpu_benchmark ;;
  gpu-watch) cmd_gpu_watch ;;
  ""|-h|--help|help) usage ;;
  *) die "unknown command: $cmd (run ./tools/mp.sh --help)" ;;
esac
