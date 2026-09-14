#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""GPU/CPU fusion scaling benchmark.

Answers honestly: for which N does GPU break even, what is the host-device transfer
overhead, and does GPU output match CPU within tolerance. Runs CPU-only when CuPy/CUDA
is unavailable.

Example:
    python benchmarks/gpu_fusion_scaling.py \\
        --methods avg weighted --n-objects 1 10 100 1000 \\
        --obs-per-object 2 4 --iters 50 --backend both \\
        --out evidence/experiments/gpu_fusion_scaling_001.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def _gen_observations(n_objects: int, obs_per_object: int, seed: int = 1234):
    rng = random.Random(seed)
    obs: dict[str, list[dict[str, float]]] = {}
    for i in range(n_objects):
        recs = []
        bx, by = rng.uniform(-5, 5), rng.uniform(-5, 5)
        for _ in range(obs_per_object):
            recs.append(
                {
                    "x": bx + rng.uniform(-0.05, 0.05),
                    "y": by + rng.uniform(-0.05, 0.05),
                    "confidence": rng.uniform(0.5, 1.0),
                    "rmse": rng.uniform(0.001, 0.02),
                }
            )
        obs[f"obj_{i:07d}"] = recs
    return obs


def _percentile(samples: list[float], q: float) -> float:
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[idx]


def _rmse(cpu_out: dict, gpu_out: dict) -> tuple[float, float]:
    keys = set(cpu_out) & set(gpu_out)
    if not keys:
        return (0.0, 0.0)
    se = 0.0
    max_abs = 0.0
    for k in keys:
        cx, cy = cpu_out[k]
        gx, gy = gpu_out[k]
        se += (cx - gx) ** 2 + (cy - gy) ** 2
        max_abs = max(max_abs, abs(cx - gx), abs(cy - gy))
    return (math.sqrt(se / len(keys)), max_abs)


@dataclass
class BenchRow:
    backend: str
    n_objects: int
    obs_per_object: int
    method: str
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    throughput_obs_per_s: float
    output_rmse_vs_cpu: float | None
    max_abs_diff: float | None


FIELDS = list(BenchRow.__dataclass_fields__.keys())


def _time_backend(backend, obs, method, iters, warmup) -> tuple[list[float], dict]:
    for _ in range(warmup):
        backend.fuse_xy(obs, method=method)
        backend.synchronize()
    samples: list[float] = []
    out: dict = {}
    for _ in range(iters):
        backend.synchronize()
        t0 = time.perf_counter_ns()
        out = backend.fuse_xy(obs, method=method)
        backend.synchronize()
        samples.append((time.perf_counter_ns() - t0) / 1e6)
    return samples, out


def _row(backend_name, n, k, method, samples, throughput_n, rmse, max_abs) -> BenchRow:
    return BenchRow(
        backend=backend_name,
        n_objects=n,
        obs_per_object=k,
        method=method,
        iterations=len(samples),
        p50_ms=round(_percentile(samples, 0.50), 6),
        p95_ms=round(_percentile(samples, 0.95), 6),
        p99_ms=round(_percentile(samples, 0.99), 6),
        mean_ms=round(sum(samples) / len(samples), 6) if samples else 0.0,
        min_ms=round(min(samples), 6) if samples else 0.0,
        max_ms=round(max(samples), 6) if samples else 0.0,
        throughput_obs_per_s=round(throughput_n, 2),
        output_rmse_vs_cpu=rmse,
        max_abs_diff=max_abs,
    )


def run(args) -> list[BenchRow]:
    from metriplane.compute.cpu_numpy import CpuNumpyBackend

    try:
        from metriplane.compute.gpu_cupy import GpuCupyBackend
    except Exception:
        GpuCupyBackend = None  # type: ignore

    want = args.backend
    cpu = CpuNumpyBackend()
    gpu = None
    gpu_reason = None
    if want in ("gpu", "both"):
        if GpuCupyBackend is None:
            gpu_reason = "cupy import failed"
        else:
            try:
                gpu = GpuCupyBackend(device=0)
            except Exception as e:
                gpu_reason = f"{type(e).__name__}: {e}"
    if gpu_reason:
        print(f"# GPU unavailable: {gpu_reason}", file=sys.stderr)
        if args.require_gpu:
            raise SystemExit(2)

    rows: list[BenchRow] = []
    for n in args.n_objects:
        for k in args.obs_per_object:
            obs = _gen_observations(n, k, seed=args.seed)
            n_obs = n * k
            for method in args.methods:
                cpu_samples, cpu_out = _time_backend(cpu, obs, method, args.iters, args.warmup)
                if want in ("cpu", "both"):
                    tput = n_obs / (sum(cpu_samples) / len(cpu_samples) / 1000.0)
                    rows.append(_row("cpu_numpy", n, k, method, cpu_samples, tput, None, None))
                if gpu is not None:
                    gpu_samples, gpu_out = _time_backend(gpu, obs, method, args.iters, args.warmup)
                    rmse, max_abs = _rmse(cpu_out, gpu_out)
                    tput = n_obs / (sum(gpu_samples) / len(gpu_samples) / 1000.0)
                    rows.append(
                        _row(
                            gpu.name,
                            n,
                            k,
                            method,
                            gpu_samples,
                            tput,
                            round(rmse, 9),
                            round(max_abs, 9),
                        )
                    )
    return rows


def write_csv(rows: list[BenchRow], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: getattr(r, k) for k in FIELDS})


def write_report(rows: list[BenchRow], path: str) -> None:
    import platform

    lines = [
        "# GPU Fusion Scaling Benchmark",
        "",
        f"- host: {platform.platform()}",
        f"- python: {platform.python_version()}",
        f"- processor: {platform.processor() or 'unknown'}",
        "",
        "## Results (median latency per fuse call)",
        "",
        "| backend | n_objects | obs | method | p50_ms | p95_ms | throughput_obs_s | rmse_vs_cpu |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.backend} | {r.n_objects} | {r.obs_per_object} | {r.method} | "
            f"{r.p50_ms} | {r.p95_ms} | {r.throughput_obs_per_s} | "
            f"{r.output_rmse_vs_cpu if r.output_rmse_vs_cpu is not None else '-'} |"
        )
    backends = {r.backend for r in rows}
    gpu_backends = backends - {"cpu_numpy"}
    lines += ["", "## Break-even analysis", ""]
    if gpu_backends and "cpu_numpy" in backends:
        gpu_name = sorted(gpu_backends)[0]
        # Per (n, obs, method), compare CPU vs GPU p50.
        cpu = {
            (r.n_objects, r.obs_per_object, r.method): r.p50_ms
            for r in rows
            if r.backend == "cpu_numpy"
        }
        gpu = {
            (r.n_objects, r.obs_per_object, r.method): r.p50_ms
            for r in rows
            if r.backend == gpu_name
        }
        crossover_n = None
        for key in sorted(cpu.keys() & gpu.keys()):
            if gpu[key] <= cpu[key] and crossover_n is None:
                crossover_n = key[0]
        if crossover_n is not None:
            lines.append(
                f"GPU (`{gpu_name}`) first matches or beats CPU at n_objects = {crossover_n}."
            )
        else:
            max_n = max(r.n_objects for r in rows)
            lines.append(
                f"GPU (`{gpu_name}`) did **not** beat CPU at any tested size "
                f"(up to n_objects = {max_n}). For this vectorized bincount "
                f"aggregation, host-device transfer dominates and CPU NumPy wins. "
                f"This is the honest result; do not claim a GPU speedup for this "
                f"workload."
            )
    else:
        lines.append(
            "CPU-only run: no GPU available on this host, so no break-even point "
            "is reported. Re-run with `--backend both` on a CUDA host."
        )
    lines += [
        "",
        "## Limitations",
        "",
        "- Synthetic observations; real workloads differ.",
        "- Timing includes host-device transfer for GPU (intentional, honest).",
        "- Single-process, single-stream measurement.",
        "",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("gpu_fusion_scaling")
    p.add_argument("--methods", nargs="+", default=["avg", "weighted"])
    p.add_argument("--n-objects", nargs="+", type=int, default=[1, 10, 100, 1000])
    p.add_argument("--obs-per-object", nargs="+", type=int, default=[2, 4])
    p.add_argument("--iters", type=int, default=50)
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--backend", choices=["cpu", "gpu", "both"], default="both")
    p.add_argument("--require-gpu", action="store_true", default=False)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--out", default=None)
    p.add_argument("--report", default=None)
    args = p.parse_args(argv)

    rows = run(args)
    if args.out:
        write_csv(rows, args.out)
        print(f"wrote {len(rows)} rows to {args.out}")
    if args.report:
        write_report(rows, args.report)
        print(f"wrote report to {args.report}")
    if not args.out and not args.report:
        for r in rows:
            print(
                f"{r.backend}  n={r.n_objects}  obs={r.obs_per_object}  "
                f"{r.method}  p50={r.p50_ms}ms  tput={r.throughput_obs_per_s}/s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
