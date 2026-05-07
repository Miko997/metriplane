from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from metriplane.compute.cpu_numpy import CpuNumpyBackend
from metriplane.compute.gpu_cupy import GpuCupyBackend, GpuUnavailable
from metriplane.compute.interface import FusionComputeBackend


def _percentile(xs: Sequence[float], p: float) -> float:
    if not xs:
        return float("nan")
    if p <= 0:
        return float(min(xs))
    if p >= 100:
        return float(max(xs))
    ys = sorted(float(x) for x in xs)
    k = (len(ys) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(ys[int(k)])
    d0 = ys[int(f)] * (c - k)
    d1 = ys[int(c)] * (k - f)
    return float(d0 + d1)


def _run_cmd(cmd: List[str], *, timeout_s: float = 2.0) -> str | None:
    try:
        p = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout_s)
        return p.stdout.strip()
    except Exception:
        return None


def _nvidia_smi_snapshot() -> Dict[str, Any] | None:
    if shutil.which("nvidia-smi") is None:
        return None

    # Minimal snapshot: name and utilization
    out = _run_cmd(
        [
            "nvidia-smi",
            "--query-gpu=name,utilization.gpu,utilization.memory",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return None

    # If multiple GPUs, take first line (device selection is handled elsewhere)
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        return None

    def _as_int(s: str) -> int | None:
        try:
            return int(s)
        except Exception:
            return None

    return {
        "gpu_name": parts[0],
        "util_gpu_pct": _as_int(parts[1]),
        "util_mem_pct": _as_int(parts[2]),
    }


def _make_backend(name: str, *, device: int) -> FusionComputeBackend | None:
    nm = str(name).strip().lower()
    if nm == "cpu":
        return CpuNumpyBackend()
    if nm == "gpu":
        try:
            return GpuCupyBackend(device=int(device))
        except GpuUnavailable:
            return None
    raise ValueError(f"unknown backend: {name}")


def _synchronize(backend: FusionComputeBackend) -> None:
    try:
        backend.synchronize()
    except Exception:
        pass


def _make_synth_observations(*, n_objects: int, n_cams: int, seed: int) -> Dict[str, List[Dict[str, Any]]]:
    rnd = random.Random(int(seed))

    obs_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for i in range(int(n_objects)):
        oid = str(i + 1)
        x0 = rnd.random() * 1.0
        y0 = rnd.random() * 0.5
        items: List[Dict[str, Any]] = []
        for c in range(int(n_cams)):
            # camera-specific noise
            nx = rnd.gauss(0.0, 0.005)
            ny = rnd.gauss(0.0, 0.005)
            rmse = max(0.005, abs(rnd.gauss(0.02, 0.01)))
            items.append({"x": x0 + nx, "y": y0 + ny, "rmse": rmse, "confidence": 1.0, "camera_id": f"cam{c}"})
        obs_by_id[oid] = items

    return obs_by_id


def _parse_int_list(s: str) -> List[int]:
    out: List[int] = []
    for part in str(s).split(","):
        p = part.strip()
        if not p:
            continue
        out.append(int(p))
    return out


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="M9.6 benchmark: compare CPU NumPy vs GPU CuPy backends for fuse_xy()",
    )
    ap.add_argument("--out-csv", type=Path, default=Path("compute_backend_comparison.csv"))
    ap.add_argument("--method", choices=["avg", "weighted"], default="weighted")
    ap.add_argument("--backends", default="cpu,gpu", help="comma-separated list: cpu,gpu")
    ap.add_argument("--objects", default="1,10,50,200,1000", help="comma-separated object counts")
    ap.add_argument("--cams", type=int, default=2)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--warmup-iters", type=int, default=50)
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--device", type=int, default=0)

    args = ap.parse_args(argv)

    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    backends = [b.strip() for b in str(args.backends).split(",") if b.strip()]
    obj_counts = _parse_int_list(str(args.objects))

    fieldnames = [
        "backend",
        "backend_name",
        "device",
        "method",
        "n_objects",
        "n_cams",
        "iters",
        "warmup_iters",
        "p50_ms",
        "p95_ms",
        "throughput_hz",
        "gpu_name",
        "gpu_util_pct_before",
        "gpu_util_pct_after",
        "gpu_mem_util_pct_before",
        "gpu_mem_util_pct_after",
        "note",
    ]

    rows: List[Dict[str, Any]] = []

    for n_obj in obj_counts:
        obs = _make_synth_observations(n_objects=int(n_obj), n_cams=int(args.cams), seed=int(args.seed))

        for b in backends:
            backend = _make_backend(b, device=int(args.device))
            if backend is None:
                rows.append(
                    {
                        "backend": b,
                        "backend_name": "(unavailable)",
                        "device": int(args.device),
                        "method": str(args.method),
                        "n_objects": int(n_obj),
                        "n_cams": int(args.cams),
                        "iters": int(args.iters),
                        "warmup_iters": int(args.warmup_iters),
                        "p50_ms": float("nan"),
                        "p95_ms": float("nan"),
                        "throughput_hz": float("nan"),
                        "gpu_name": None,
                        "gpu_util_pct_before": None,
                        "gpu_util_pct_after": None,
                        "gpu_mem_util_pct_before": None,
                        "gpu_mem_util_pct_after": None,
                        "note": "gpu backend unavailable",
                    }
                )
                continue

            # Warmup (important for GPU)
            for _ in range(int(args.warmup_iters)):
                backend.fuse_xy(obs, method=str(args.method))
                _synchronize(backend)

            smi_before = _nvidia_smi_snapshot() or {}

            lat_ms: List[float] = []
            t0 = time.perf_counter()
            for _ in range(int(args.iters)):
                t1 = time.perf_counter()
                backend.fuse_xy(obs, method=str(args.method))
                _synchronize(backend)
                lat_ms.append((time.perf_counter() - t1) * 1000.0)
            total_s = time.perf_counter() - t0

            smi_after = _nvidia_smi_snapshot() or {}

            p50 = _percentile(lat_ms, 50)
            p95 = _percentile(lat_ms, 95)
            thr = (float(args.iters) / total_s) if total_s > 1e-9 else float("nan")

            rows.append(
                {
                    "backend": b,
                    "backend_name": backend.name,
                    "device": int(args.device),
                    "method": str(args.method),
                    "n_objects": int(n_obj),
                    "n_cams": int(args.cams),
                    "iters": int(args.iters),
                    "warmup_iters": int(args.warmup_iters),
                    "p50_ms": float(p50),
                    "p95_ms": float(p95),
                    "throughput_hz": float(thr),
                    "gpu_name": smi_before.get("gpu_name") or smi_after.get("gpu_name"),
                    "gpu_util_pct_before": smi_before.get("util_gpu_pct"),
                    "gpu_util_pct_after": smi_after.get("util_gpu_pct"),
                    "gpu_mem_util_pct_before": smi_before.get("util_mem_pct"),
                    "gpu_mem_util_pct_after": smi_after.get("util_mem_pct"),
                    "note": "",
                }
            )

            print(
                json.dumps(
                    {
                        "backend": backend.name,
                        "n_objects": int(n_obj),
                        "method": str(args.method),
                        "p50_ms": p50,
                        "p95_ms": p95,
                        "throughput_hz": thr,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )

    # Write CSV
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
