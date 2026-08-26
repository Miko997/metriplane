#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail

# Metriplane DEMO_ALL: "run everything and map PASS/FAIL"
#
# Produces:
#   <platform-runs-dir>/demo_all_YYYYmmdd_HHMMSS/
#     - *.log (one per step)
#     - manifest.tsv (step/status/rc/log/cmd)
#
# Notes:
# - You do NOT need to activate a venv; we always call .venv/bin/python directly.
# - Omniverse tools are environment-specific: help runs are skipped unless --with-omniverse.
# - tools/session_health_summary.py expects ONE positional arg (session.jsonl) and does not accept flags.
#
# Usage examples:
#   ./scripts/DEMO_ALL.sh
#   ./scripts/DEMO_ALL.sh --with-opencv
#   ./scripts/DEMO_ALL.sh --vt-demo-all 5
#   ./scripts/DEMO_ALL.sh --with-opencv --run-shell-help --vt-demo-all 5 --with-docker
#
# Exit code:
#   0 if no FAIL steps
#   1 if any FAIL steps

usage() {
  cat <<'EOF'
Usage: ./scripts/DEMO_ALL.sh [options]

Options:
  --with-opencv        Install opencv-contrib-python + run cv2 smoke check
  --with-docker        Run tools/docker_smoke_test.sh (if present)
  --with-hardware      Run M6–M9 runbook scripts (requires cameras/hardware)
  --run-shell-help     Try running --help for shell scripts (WARN on nonzero)
  --with-omniverse     Also run --help for tools/omniverse/*.py (requires Omni env)
  --vt-demo-all [sec]  Run tools/mp.sh preflight + demo-all (optional faster sec)
  --fail-fast          Stop at first FAIL
  -h, --help           Show this help

Environment:
  RUNS (optional)      Where mp.sh writes run directories (default: platform runs directory)
EOF
}

# ----------------------------- arg parsing -----------------------------
WITH_OPENCV=0
WITH_DOCKER=0
WITH_HARDWARE=0
RUN_SHELL_HELP=0
WITH_OMNIVERSE=0
METRIPLANE_DEMO_ALL=0
METRIPLANE_DEMO_ALL_SEC=""
FAIL_FAST=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-opencv) WITH_OPENCV=1; shift ;;
    --with-docker) WITH_DOCKER=1; shift ;;
    --with-hardware) WITH_HARDWARE=1; shift ;;
    --run-shell-help) RUN_SHELL_HELP=1; shift ;;
    --with-omniverse) WITH_OMNIVERSE=1; shift ;;
    --vt-demo-all)
      METRIPLANE_DEMO_ALL=1
      if [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]]; then
        METRIPLANE_DEMO_ALL_SEC="$2"
        shift 2
      else
        METRIPLANE_DEMO_ALL_SEC=""
        shift
      fi
      ;;
    --fail-fast) FAIL_FAST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

# ----------------------------- paths -----------------------------
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT/.venv"
PYTHON="$VENV_DIR/bin/python"
RUN_ID="demo_all_$(date +%Y%m%d_%H%M%S)"

if [[ "${RUNS:-}" =~ [^[:space:]] ]]; then
  RUNS_DIR="$RUNS"
else
  PATHS_PYTHON="python3"
  if [[ -x "$PYTHON" ]]; then
    PATHS_PYTHON="$PYTHON"
  fi
  RUNS_DIR="$(cd "$ROOT" && "$PATHS_PYTHON" -c \
    '
import sys
from metriplane.paths import PlatformPathError, resolve_platform_paths

try:
    print(resolve_platform_paths().runs_dir)
except PlatformPathError as exc:
    print(f"platform path error: {exc}", file=sys.stderr)
    raise SystemExit(2)
')"
fi
LOG_DIR="$RUNS_DIR/$RUN_ID"
mkdir -p "$LOG_DIR"

MANIFEST="$LOG_DIR/manifest.tsv"
printf "step\tstatus\trc\tseconds\tlog\tcmd\n" > "$MANIFEST"

echo "Repo root : $ROOT"
echo "Venv dir  : $VENV_DIR"
echo "Python    : $PYTHON"
echo "Log dir   : $LOG_DIR"
echo "RUNS dir  : $RUNS_DIR"

# ----------------------------- bookkeeping -----------------------------
PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
declare -a FAIL_LIST=()

qcmd() { printf '%q ' "$@"; }

record_manifest() {
  local step="$1" status="$2" rc="$3" sec="$4" log="$5"; shift 5
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$step" "$status" "$rc" "$sec" "$log" "$(qcmd "$@")" >> "$MANIFEST"
}

step_header() {
  local step="$1" log="$2"; shift 2
  echo
  echo "================================================================================"
  echo "STEP: $step"
  echo "LOG : $log"
  echo -n "CMD : "; qcmd "$@"; echo
  echo "================================================================================"
}

run_step() {
  local step="$1"; shift
  local log="$LOG_DIR/${step//\//_}.log"
  local start rc end sec
  step_header "$step" "$log" "$@"
  start="$(date +%s)"
  set +e
  "$@" >"$log" 2>&1
  rc=$?
  set -e
  end="$(date +%s)"
  sec=$((end - start))

  if [[ $rc -eq 0 ]]; then
    echo "✅ PASS: $step"
    PASS_COUNT=$((PASS_COUNT + 1))
    record_manifest "$step" "PASS" "$rc" "$sec" "$log" "$@"
    return 0
  fi

  echo "❌ FAIL($rc): $step"
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAIL_LIST+=("$step ($log)")
  record_manifest "$step" "FAIL" "$rc" "$sec" "$log" "$@"

  if [[ "$FAIL_FAST" -eq 1 ]]; then
    exit 1
  fi
  return 0
}

run_step_warn() {
  local step="$1"; shift
  local log="$LOG_DIR/${step//\//_}.log"
  local start rc end sec
  step_header "$step" "$log" "$@"
  start="$(date +%s)"
  set +e
  "$@" >"$log" 2>&1
  rc=$?
  set -e
  end="$(date +%s)"
  sec=$((end - start))

  if [[ $rc -eq 0 ]]; then
    echo "✅ PASS: $step"
    PASS_COUNT=$((PASS_COUNT + 1))
    record_manifest "$step" "PASS" "$rc" "$sec" "$log" "$@"
  else
    echo "⚠️  WARN($rc): $step"
    WARN_COUNT=$((WARN_COUNT + 1))
    record_manifest "$step" "WARN" "$rc" "$sec" "$log" "$@"
  fi
  return 0
}

skip_step() {
  local step="$1" reason="${2:-}"
  echo "⏭️  SKIP: $step - $reason"
  SKIP_COUNT=$((SKIP_COUNT + 1))
  # log/cmd are "-" for skips
  printf "%s\tSKIP\t0\t0\t-\t%s\n" "$step" "$reason" >> "$MANIFEST"
}

# ----------------------------- steps -----------------------------

# venv create (avoid repo-root stdlib shadowing by creating from /)
if [[ -x "$PYTHON" ]]; then
  skip_step "venv_create" "venv already exists"
else
  run_step "venv_create" bash -lc "cd / && python3 -m venv '$VENV_DIR'"
fi

# sanity check python exists now
if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: venv python not found at $PYTHON" >&2
  exit 2
fi

run_step "pip_bootstrap" "$PYTHON" -m pip install -U "pip<26" wheel "setuptools<80"
run_step "pip_install_editable_dev" "$PYTHON" -m pip install -e ".[dev]"

if [[ "$WITH_OPENCV" -eq 1 ]]; then
  run_step "pip_install_opencv_contrib" "$PYTHON" -m pip install -U opencv-contrib-python
  run_step "cv2_smoke" "$PYTHON" -c "import cv2; print('cv2:', cv2.__version__, 'aruco:', hasattr(cv2,'aruco'))"
else
  skip_step "pip_install_opencv_contrib" "use --with-opencv"
  skip_step "cv2_smoke" "use --with-opencv"
fi

run_step "python_version" "$PYTHON" -V
run_step "pip_freeze_head" bash -lc "'$PYTHON' -m pip freeze | sed -n '1,120p'"

run_step "compileall_repo" bash -lc "cd '$ROOT' && '$PYTHON' -m compileall -q metriplane tools benchmarks"

run_step "import_key_modules" "$PYTHON" -c \
"import metriplane; from metriplane import cli, config, schema; from metriplane.streaming import ws_server; print('imports OK')"

# pytest: disable plugin autoload to avoid ROS2/launch_testing importing the system pytest plugins
run_step "pytest" bash -lc "cd '$ROOT' && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 '$PYTHON' -m pytest -q"

# Python scripts: per-file compile + help (with a few special-case skips)
run_py_compile_and_help() {
  local rel="$1"
  local abs="$ROOT/$rel"

  run_step "py_compile_${rel}" "$PYTHON" -m py_compile "$abs"

  # Special cases:
  if [[ "$rel" == "tools/session_health_summary.py" ]]; then
    # No --help; it expects a session.jsonl arg.
    skip_step "py_help_${rel}" "expects 1 positional arg (session.jsonl); no --help/flags"
    return 0
  fi

  if [[ "$rel" == "tools/plot_compute_backend_comparison.py" ]]; then
    # Usually data-driven; we validate it indirectly via mp.sh gpu-benchmark artifacts.
    skip_step "py_help_${rel}" "data-driven tool; validate via gpu-benchmark artifacts instead"
    return 0
  fi

  if [[ "$rel" == tools/omniverse/* ]]; then
    if [[ "$WITH_OMNIVERSE" -eq 1 ]]; then
      run_step "py_help_${rel}" env MPLBACKEND=Agg "$PYTHON" "$abs" --help
    else
      skip_step "py_help_${rel}" "use --with-omniverse (Omniverse env required)"
    fi
    return 0
  fi

  # Default: --help should be safe for argparse CLIs.
  run_step "py_help_${rel}" env MPLBACKEND=Agg "$PYTHON" "$abs" --help
}

# Benchmarks
if compgen -G "$ROOT/benchmarks/*.py" > /dev/null; then
  for f in "$ROOT"/benchmarks/*.py; do
    rel="benchmarks/$(basename "$f")"
    run_py_compile_and_help "$rel"
  done
fi

# Tools (including nested demos)
while IFS= read -r -d '' f; do
  rel="${f#$ROOT/}"
  run_py_compile_and_help "$rel"
done < <(find "$ROOT/tools" -name '*.py' -print0 | sort -z)

# Shell scripts: syntax checks
while IFS= read -r -d '' sh; do
  rel="${sh#$ROOT/}"
  run_step "bash_syntax_${rel}" bash -n "$sh"
done < <(find "$ROOT/scripts" "$ROOT/tools" -name '*.sh' -print0 2>/dev/null | sort -z)

# Optional: shell help probes (WARN on failure; lots of scripts won't implement --help)
if [[ "$RUN_SHELL_HELP" -eq 1 ]]; then
  while IFS= read -r -d '' sh; do
    rel="${sh#$ROOT/}"
    run_step_warn "bash_help_${rel}" bash "$sh" --help
  done < <(find "$ROOT/scripts" "$ROOT/tools" -name '*.sh' -print0 2>/dev/null | sort -z)
else
  skip_step "bash_help_*" "use --run-shell-help"
fi

# Optional: mp.sh demo-all (the real end-to-end proof harness)
if [[ "$METRIPLANE_DEMO_ALL" -eq 1 ]]; then
  run_step "vt_preflight" bash -lc "cd '$ROOT' && export RUNS='$RUNS_DIR' && mkdir -p '$RUNS_DIR' && ./tools/mp.sh preflight"

  if [[ -n "$METRIPLANE_DEMO_ALL_SEC" ]]; then
    run_step "vt_demo_all" bash -lc "cd '$ROOT' && export RUNS='$RUNS_DIR' && mkdir -p '$RUNS_DIR' && ./tools/mp.sh demo-all '$METRIPLANE_DEMO_ALL_SEC'"
  else
    run_step "vt_demo_all" bash -lc "cd '$ROOT' && export RUNS='$RUNS_DIR' && mkdir -p '$RUNS_DIR' && ./tools/mp.sh demo-all"
  fi

  # Post-check: run session_health_summary on the newest session.jsonl we can find
  latest_session="$(
    (find "$RUNS_DIR" -type f -name 'session.jsonl' -printf '%T@ %p\n' 2>/dev/null || true) \
    | sort -nr | head -n 1 | awk '{print $2}'
  )"

  if [[ -n "${latest_session:-}" && -f "${latest_session:-}" ]]; then
    run_step "session_health_summary_latest" bash -lc \
      "cd '$ROOT' && '$PYTHON' tools/session_health_summary.py '$latest_session' > '$LOG_DIR/session_health_summary_latest.md'"
  else
    skip_step "session_health_summary_latest" "no session.jsonl found (run vt demo or produce a session first)"
  fi

  # Post-check: if gpu-benchmark ran, show png/csv artifacts
  latest_gpu_dir="$(
    (find "$RUNS_DIR" -maxdepth 2 -type d -name 'gpu_benchmark_*' -printf '%T@ %p\n' 2>/dev/null || true) \
    | sort -nr | head -n 1 | awk '{print $2}'
  )"

  if [[ -n "${latest_gpu_dir:-}" && -d "${latest_gpu_dir:-}" ]]; then
    run_step "gpu_benchmark_artifacts" bash -lc "ls -lah '$latest_gpu_dir' | egrep 'png|csv|session' || true"
  else
    skip_step "gpu_benchmark_artifacts" "no gpu_benchmark_* dir found under RUNS"
  fi
else
  skip_step "vt_preflight" "use --vt-demo-all [sec]"
  skip_step "vt_demo_all" "use --vt-demo-all [sec]"
fi

# Optional: docker smoke
if [[ "$WITH_DOCKER" -eq 1 ]]; then
  if [[ -f "$ROOT/tools/docker_smoke_test.sh" ]]; then
    run_step "docker_smoke_test" bash -lc "cd '$ROOT' && bash tools/docker_smoke_test.sh"
  else
    skip_step "docker_smoke_test" "tools/docker_smoke_test.sh not found"
  fi
else
  skip_step "docker_smoke_test" "use --with-docker"
fi

# Optional: hardware runbooks (M6–M9)
if [[ "$WITH_HARDWARE" -eq 1 ]]; then
  for s in scripts/M6_run_baseline.sh scripts/M7_run_multicam_fusion.sh scripts/M8_provenance.sh scripts/M9_full.sh; do
    if [[ -f "$ROOT/$s" ]]; then
      run_step "hardware_${s}" bash -lc "cd '$ROOT' && bash '$s'"
    else
      skip_step "hardware_${s}" "not found"
    fi
  done
else
  skip_step "hardware_demos" "use --with-hardware"
fi

# ----------------------------- summary -----------------------------
echo
echo "====================== SUMMARY ======================"
echo "Logs: $LOG_DIR"
echo "PASS: $PASS_COUNT  WARN: $WARN_COUNT  FAIL: $FAIL_COUNT  SKIP: $SKIP_COUNT"
echo "Manifest: $MANIFEST"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo
  echo "❌ FAILED:"
  for item in "${FAIL_LIST[@]}"; do
    echo "  - $item"
  done
  exit 1
fi

exit 0
