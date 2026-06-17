#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail

export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
