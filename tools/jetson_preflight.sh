#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# Jetson / edge preflight check for Metriplane.
# Verifies OS/arch, Python, camera devices, NVIDIA tooling, ports, and import.
# Usage: tools/jetson_preflight.sh [--json]
set -uo pipefail

JSON=0
[ "${1:-}" = "--json" ] && JSON=1

os_arch="$(uname -s)/$(uname -m)"
py_version="$(python3 --version 2>&1 | awk '{print $2}')"

cameras="$(ls /dev/video* 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
[ -z "$cameras" ] && cameras="none"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia="nvidia-smi"
elif command -v tegrastats >/dev/null 2>&1; then
  nvidia="tegrastats"
else
  nvidia="none"
fi

cuda="no"
python3 -c "import cupy" >/dev/null 2>&1 && cuda="cupy"

port_8000="free"
(python3 -c "import socket;s=socket.socket();s.bind(('127.0.0.1',8000));s.close()" >/dev/null 2>&1) || port_8000="in_use"

mp_import="fail"
python3 -c "import metriplane" >/dev/null 2>&1 && mp_import="ok"

if [ "$JSON" -eq 1 ]; then
  printf '{"os_arch":"%s","python":"%s","cameras":"%s","nvidia":"%s","cuda":"%s","port_8000":"%s","metriplane_import":"%s"}\n' \
    "$os_arch" "$py_version" "$cameras" "$nvidia" "$cuda" "$port_8000" "$mp_import"
else
  echo "Metriplane Jetson/edge preflight"
  echo "  os/arch:           $os_arch"
  echo "  python:            $py_version"
  echo "  camera devices:    $cameras"
  echo "  nvidia tooling:    $nvidia"
  echo "  cuda (cupy):       $cuda"
  echo "  port 8000:         $port_8000"
  echo "  metriplane import: $mp_import"
fi

[ "$mp_import" = "ok" ] && exit 0 || exit 1
