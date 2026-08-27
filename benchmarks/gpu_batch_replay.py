#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Batch replay fusion benchmark.

Replays a session JSONL, grouping frames into batches and running fusion-like
aggregation per batch to measure per-frame throughput by backend and batch size.

Example:
    python benchmarks/gpu_batch_replay.py --session s.jsonl \\
        --batch-sizes 1 8 32 --backend cpu --out /tmp/batch.csv
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path


def _load_frames(session_path: str):
    from metriplane.sentinel.engine import iter_frames

    frames = []
    for f in iter_frames(session_path):
        objs = f.fused if f.fused is not None else f.objects
        recs = [
            {
                "x": o.pos_world[0],
                "y": o.pos_world[1],
                "confidence": o.confidence or 1.0,
                "rmse": 0.01,
            }
            for o in objs
            if o.pos_world is not None
        ]
        frames.append((str(f.frame_id), recs))
    return frames


def run(
    session_path: str,
    batch_sizes: list[int],
    backend_name: str,
    method: str = "avg",
    warmup: int = 3,
):
    from metriplane.compute.cpu_numpy import CpuNumpyBackend

    backend = CpuNumpyBackend()
    if backend_name == "gpu":
        try:
            from metriplane.compute.gpu_cupy import GpuCupyBackend

            backend = GpuCupyBackend(device=0)
        except Exception as e:
            print(f"# GPU unavailable ({e}); using CPU")

    frames = _load_frames(session_path)
    if not frames:
        raise SystemExit("no frames in session")
    total_objs = sum(len(recs) for _, recs in frames)

    rows = []
    for bs in batch_sizes:
        # warmup
        for _ in range(warmup):
            for i in range(0, len(frames), bs):
                obs = {f"{fid}_{j}": recs for fid, recs in frames[i : i + bs] for j in [0]}
                backend.fuse_xy(obs, method=method)
                backend.synchronize()
        backend.synchronize()
        t0 = time.perf_counter_ns()
        for i in range(0, len(frames), bs):
            obs = {f"{fid}_{j}": recs for fid, recs in frames[i : i + bs] for j in [0]}
            backend.fuse_xy(obs, method=method)
        backend.synchronize()
        total_s = (time.perf_counter_ns() - t0) / 1e9
        per_frame_ms = (total_s / len(frames)) * 1000.0
        rows.append(
            {
                "batch_size": bs,
                "frames": len(frames),
                "objects_per_frame": round(total_objs / len(frames), 2),
                "backend": backend.name,
                "p50_ms_per_frame": round(per_frame_ms, 6),
                "throughput_frames_per_s": round(len(frames) / total_s, 2),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("gpu_batch_replay")
    p.add_argument("--session", required=True)
    p.add_argument("--batch-sizes", nargs="+", type=int, default=[1, 8, 32])
    p.add_argument("--backend", choices=["cpu", "gpu"], default="cpu")
    p.add_argument("--method", default="avg")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    rows = run(args.session, args.batch_sizes, args.backend, args.method)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {args.out}")
    else:
        for r in rows:
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
