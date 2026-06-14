#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Source this AFTER activating the venv:
#   source ~/metriplane-venv/bin/activate
#   source tools/env/vt_cuda13_env.sh
#
# Purpose:
#   Point CUDA_PATH/CUDA_HOME + PATH + LD_LIBRARY_PATH at the pip-installed CUDA 13 toolkit
#   living under: site-packages/nvidia/cu13  (installed via: pip install "cuda-toolkit[all]")

# If someone runs it instead of sourcing it, fail with a clear message.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "[vt_cuda13_env] This script must be sourced, not executed." >&2
  echo "[vt_cuda13_env] Usage: source tools/env/vt_cuda13_env.sh" >&2
  exit 1
fi

_vt_err() { echo "[vt_cuda13_env] $*" >&2; }
_vt_prepend() {
  # Prepend $2 to env var named $1 if not already present (colon-separated).
  local var="$1"
  local val="$2"
  [[ -z "$val" ]] && return 0
  local cur="${!var:-}"
  case ":$cur:" in
    *":$val:"*) : ;; # already present
    *) export "$var=$val${cur:+:$cur}" ;;
  esac
}

# Require venv (we locate CUDA inside this interpreter's site-packages)
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  _vt_err "VIRTUAL_ENV is not set. Activate your venv first."
  return 1
fi

CUDA_ROOT="$(python - <<'PY'
import importlib.util
try:
    spec = importlib.util.find_spec("nvidia.cu13")
except ModuleNotFoundError:
    spec = None
if spec is None or not spec.submodule_search_locations:
    raise SystemExit(
        "nvidia.cu13 not found in this interpreter.\n"
        "Install in the ACTIVE venv:\n"
        "  pip install -U cupy-cuda13x \"cuda-toolkit[all]\""
    )
print(next(iter(spec.submodule_search_locations)))
PY
)"

export CUDA_PATH="$CUDA_ROOT"
export CUDA_HOME="$CUDA_ROOT"

# Toolchain + runtime libs
_vt_prepend PATH "$CUDA_ROOT/bin"
if [[ -d "$CUDA_ROOT/lib" ]]; then
  _vt_prepend LD_LIBRARY_PATH "$CUDA_ROOT/lib"
fi
if [[ -d "$CUDA_ROOT/lib64" ]]; then
  _vt_prepend LD_LIBRARY_PATH "$CUDA_ROOT/lib64"
fi

# Optional: headers (useful if anything compiles extensions)
if [[ -d "$CUDA_ROOT/include" ]]; then
  _vt_prepend CPATH "$CUDA_ROOT/include"
fi

echo "[vt_cuda13_env] CUDA_PATH=$CUDA_PATH"
echo "[vt_cuda13_env] LD_LIBRARY_PATH starts with: ${LD_LIBRARY_PATH%%:*}"

unset -f _vt_err
unset -f _vt_prepend
