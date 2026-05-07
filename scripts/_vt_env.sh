#!/usr/bin/env bash
set -euo pipefail

# Run from anywhere; we cd to repo root.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

# Match your transcript defaults.
export RUNS="${RUNS:-~/metriplane-runs}"
export CONFIG="${CONFIG:-configs/fusion_health_300fps.yaml}"

mkdir -p "$RUNS"

# Helper: locate the newest run dir for a run-id prefix (handles suffixes like "-2")
vt_find_run_dir() {
  local rid_prefix="$1"
  local d
  d="$(ls -dt "$RUNS/${rid_prefix}"* 2>/dev/null | head -n 1 || true)"
  if [[ -z "$d" ]]; then
    echo "ERROR: could not find run dir for prefix: $rid_prefix in $RUNS" >&2
    return 1
  fi
  echo "$d"
}
