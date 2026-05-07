#!/usr/bin/env bash
set -euo pipefail
source scripts/_vt_env.sh

echo "=== M9 full run (M9.1–M9.6) ==="
./tools/mp.sh preflight

# --- Fusion CPU (baseline capture) ---
RUN_ID_CPU="m9_fusion_cpu_$(date +%Y%m%d_%H%M%S)"
DUR_CPU="${1:-10}"
echo
echo "=== (M9 baseline) fusion CPU ${DUR_CPU}s: $RUN_ID_CPU ==="
./tools/mp.sh run-fusion cpu "$DUR_CPU" "$RUN_ID_CPU"
RUN_DIR_CPU="$(vt_find_run_dir "$RUN_ID_CPU")"
echo "RUN_DIR_CPU=$RUN_DIR_CPU"

# --- Deterministic replay on CPU run (M9.1) ---
echo
echo "=== (M9.1) deterministic replay (CPU session) ==="
./tools/mp.sh deterministic-replay "$RUN_DIR_CPU/session.jsonl"

# --- Backpressure benchmark (M9.2) ---
echo
echo "=== (M9.2) backpressure benchmark ==="
./tools/mp.sh backpressure

# --- Health degrade cam1 (M9.3) ---
echo
echo "=== (M9.3) health degrade cam1 ==="
./tools/mp.sh health-degrade-cam1

# --- Provenance (M9.4 style run stamping) ---
echo
echo "=== (M9.4) provenance demo ==="
./tools/mp.sh provenance

# --- Timing breakdown (M9.5) ---
echo
echo "=== (M9.5) per-stage timing breakdown ==="
./tools/mp.sh timing-breakdown

# --- GPU smoke/equivalence/benchmark (M9.6) ---
echo
echo "=== (M9.6) GPU smoke ==="
./tools/mp.sh gpu-smoke

echo
echo "=== (M9.6) GPU equivalence (CPU vs GPU) ==="
./tools/mp.sh gpu-equivalence

echo
echo "=== (M9.6) GPU benchmark (CPU vs GPU synthetic) ==="
./tools/mp.sh gpu-benchmark

# --- Fusion GPU run + deterministic replay (matches your demo-all pattern) ---
RUN_ID_GPU="m9_fusion_gpu_$(date +%Y%m%d_%H%M%S)"
DUR_GPU="${2:-10}"
echo
echo "=== fusion GPU ${DUR_GPU}s: $RUN_ID_GPU ==="
./tools/mp.sh run-fusion gpu "$DUR_GPU" "$RUN_ID_GPU"
RUN_DIR_GPU="$(vt_find_run_dir "$RUN_ID_GPU")"
echo "RUN_DIR_GPU=$RUN_DIR_GPU"

echo
echo "=== deterministic replay (GPU session) ==="
./tools/mp.sh deterministic-replay "$RUN_DIR_GPU/session.jsonl"

# --- Bundle evidence into one folder (like your transcript) ---
OUT="$RUNS/m9_full_bundle_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"

echo
echo "=== Bundling evidence into: $OUT ==="
cp -v /tmp/replay_determinism.csv "$OUT/" 2>/dev/null || true
cp -v /tmp/backpressure_summary.csv "$OUT/" 2>/dev/null || true
cp -v /tmp/backpressure_timeseries.csv "$OUT/" 2>/dev/null || true
cp -v /tmp/backpressure_*.csv "$OUT/" 2>/dev/null || true

# GPU artifacts live under RUNS (per your transcript: gpu_equivalence_001, gpu_benchmark_001)
cp -v "$RUNS/gpu_equivalence_001/compute_equivalence.csv" "$OUT/" 2>/dev/null || true
cp -v "$RUNS/gpu_benchmark_001/compute_backend_comparison.csv" "$OUT/" 2>/dev/null || true
cp -v "$RUNS/gpu_benchmark_001/"*comparison*.png "$OUT/" 2>/dev/null || true

# Latest provenance/timing/health dirs (prefixes from your transcript)
LATEST_PROV="$(ls -dt "$RUNS/provenance_run_001"* 2>/dev/null | head -n1 || true)"
LATEST_TIME="$(ls -dt "$RUNS/timing_breakdown_001"* 2>/dev/null | head -n1 || true)"
LATEST_HEALTH="$(ls -dt "$RUNS/health_degrade_cam1_001"* 2>/dev/null | head -n1 || true)"

[[ -n "$LATEST_PROV" ]] && cp -v "$LATEST_PROV/meta.json" "$OUT/" || true
[[ -n "$LATEST_TIME" ]] && cp -v "$LATEST_TIME/latency_summary.csv" "$OUT/" || true
[[ -n "$LATEST_HEALTH" ]] && cp -v "$LATEST_HEALTH/meta.json" "$OUT/health_degrade_meta.json" || true

sha256sum "$OUT"/* | tee "$OUT/checksums.sha256" || true
echo "Bundle complete: $OUT"
