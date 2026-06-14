#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -u -o pipefail
set +H 2>/dev/null || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV_DIR="${VENV_DIR:-$ROOT/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="${LOG_DIR:-$ROOT/runs/smoke_$(date +%Y%m%d_%H%M%S)}"

DO_INSTALL=1
RUN_HARDWARE=0
RUN_DOCKER=0
INSTALL_OPENCV=0

usage() {
  cat <<USAGE
Usage: scripts/RUN_ALL_METRIPLANE_DEMOS.sh [options]

Options:
  --venv <path>        Use/create venv at <path> (default: ./.venv)
  --skip-install       Do not pip install -e .
  --install-opencv     Install opencv-contrib-python (fixes cv2 import failures)
  --with-hardware      Run scripts/M6..M9 scripts (may require cameras/calib)
  --with-docker        Run tools/docker_smoke_test.sh (if present)
  --log-dir <path>     Write logs to <path> (default: runs/smoke_TIMESTAMP)
  -h, --help           Show help

Env:
  PYTHON_BIN=python3.12
  VENV_DIR=...
  LOG_DIR=...
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --venv) VENV_DIR="$2"; shift 2;;
    --log-dir) LOG_DIR="$2"; shift 2;;
    --skip-install) DO_INSTALL=0; shift;;
    --install-opencv) INSTALL_OPENCV=1; shift;;
    --with-hardware) RUN_HARDWARE=1; shift;;
    --with-docker) RUN_DOCKER=1; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown option: $1"; usage; exit 2;;
  esac
done

mkdir -p "$LOG_DIR"

PASS_LIST=()
FAIL_LIST=()
SKIP_LIST=()

run_step() {
  local name="$1"; shift
  local log="$LOG_DIR/${name}.log"
  echo
  echo "================================================================================"
  echo "STEP: $name"
  echo "LOG : $log"
  echo "CMD : $*"
  echo "================================================================================"

  {
    echo "STEP: $name"
    echo "CMD : $*"
    echo "TIME: $(date -Is)"
    echo
    "$@"
  } >"$log" 2>&1

  local rc=$?
  if [[ $rc -eq 0 ]]; then
    echo "✅ PASS: $name"
    PASS_LIST+=("$name")
  else
    echo "❌ FAIL($rc): $name"
    FAIL_LIST+=("$name")
  fi
  return $rc
}

require_step() {
  local name="$1"; shift
  run_step "$name" "$@" || {
    echo
    echo "FATAL: required step failed: $name"
    echo "See log: $LOG_DIR/${name}.log"
    exit 1
  }
}

skip() {
  local name="$1"
  local reason="${2:-}"
  echo "⏭️  SKIP: $name ${reason:+- $reason}"
  SKIP_LIST+=("$name")
}

echo "Repo root : $ROOT"
echo "Venv dir  : $VENV_DIR"
echo "Log dir   : $LOG_DIR"

# Create venv (run from /tmp to avoid local module shadowing)
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  require_step "venv_create" bash -lc "cd /tmp && $PYTHON_BIN -m venv '$VENV_DIR'"
else
  skip "venv_create" "venv already exists"
fi

if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
  echo "FATAL: venv activation script missing: $VENV_DIR/bin/activate"
  exit 1
fi

# Activate venv
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Make Python safer vs local shadowing when running from repo root
export PYTHONSAFEPATH=1

require_step "python_version" "$PY" -V

require_step "pip_upgrade" "$PIP" install -U pip wheel setuptools

if [[ $DO_INSTALL -eq 1 ]]; then
  # dev extras may not exist; ignore failure
  run_step "pip_install_editable_dev" "$PIP" install -e ".[dev]" || true
  require_step "pip_install_editable" "$PIP" install -e .
else
  skip "pip_install" "requested --skip-install"
fi

if [[ $INSTALL_OPENCV -eq 1 ]]; then
  require_step "pip_install_opencv_contrib" "$PIP" install -U opencv-contrib-python
else
  # just report whether cv2 exists
  run_step "check_cv2" "$PY" -c "import cv2; print('cv2 OK', cv2.__version__)" || true
fi

# Ensure pytest available if tests exist
if [[ -d "$ROOT/tests" ]]; then
  run_step "ensure_pytest" "$PY" -c "import pytest; print('pytest OK')" || \
    require_step "pip_install_pytest" "$PIP" install -U pytest
else
  skip "pytest" "no tests/ directory"
fi

run_step "pip_freeze" bash -lc "$PY -m pip freeze | sed -n '1,120p'" || true

# Compile sources
run_step "compileall_repo" "$PY" -m compileall -q metriplane tools benchmarks || true

# Imports (will fail if cv2 missing and your modules import it at import-time)
run_step "import_metriplane" "$PY" -c "import metriplane; print('metriplane import OK')"
run_step "import_key_modules" "$PY" -c "from metriplane import cli, config, schema; from metriplane.streaming import ws_server; print('imports OK')" || true

# Benchmarks: --help (should work once package is installed)
for f in benchmarks/run_*.py; do
  [[ -f "$f" ]] || continue
  base="$(basename "$f" .py)"
  run_step "bench_help_${base}" "$PY" "$f" --help || true
done

# Pytest (disable plugin autoload if ROS2 pytest plugins are too aggressive)
if [[ -d "$ROOT/tests" ]]; then
  run_step "pytest" bash -lc "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$VENV_DIR/bin/python" -m pytest -q
" || true
fi

skip "hardware_demos" "use --with-hardware if you want (not enabled in this runner v2)"
skip "docker_smoke_test" "use --with-docker if you want"

echo
echo "====================== SUMMARY ======================"
echo "Logs: $LOG_DIR"
echo "PASS: ${#PASS_LIST[@]}  FAIL: ${#FAIL_LIST[@]}  SKIP: ${#SKIP_LIST[@]}"
echo

if ((${#FAIL_LIST[@]})); then
  echo "❌ FAILED:"
  printf '  - %s\n' "${FAIL_LIST[@]}"
  echo
  echo "Open logs in: $LOG_DIR"
  exit 1
fi

echo "All selected checks passed."
exit 0
