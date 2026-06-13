#!/usr/bin/env bash
# Self-contained incident reproduction for inc_0001.
# Re-runs incident detection on the bundled session excerpt and verifies the
# incident reproduces and checksums match.
set -euo pipefail
cd "$(dirname "$0")"

metriplane incidents verify-bundle .
