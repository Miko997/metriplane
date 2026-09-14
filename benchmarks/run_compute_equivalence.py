# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Tuple

from metriplane.compute.cpu_numpy import CpuNumpyBackend
from metriplane.compute.gpu_cupy import GpuCupyBackend, GpuUnavailable
from metriplane.compute.interface import FusionComputeBackend


HEADER_TYPES = {"header", "run_header", "provenance"}


@dataclass(frozen=True, slots=True)
class DiffStats:
    samples: int
    rmse_cm: float
    max_abs_diff_cm: float


def _is_header_record(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    t = obj.get("type") or obj.get("record_type")
    return str(t) in HEADER_TYPES


def _extract_obs_by_id(frame_obj: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build observations per object id from a Metriplane FrameState JSON dict.

    Uses `raw_per_camera[*].objects[*].pos_world` as XY and tries rmse from:
      - obj.extra.cam_anchor_rmse
      - camera_frame.metrics.cam_anchor_rmse

    The output schema is purposely backend-agnostic.
    """
    raw = frame_obj.get("raw_per_camera")
    if not isinstance(raw, list):
        return {}

    obs_by_id: dict[str, list[dict[str, Any]]] = {}

    for cam_fr in raw:
        if not isinstance(cam_fr, dict):
            continue
        cam_metrics = cam_fr.get("metrics")
        cam_rmse = None
        if isinstance(cam_metrics, dict) and cam_metrics.get("cam_anchor_rmse") is not None:
            try:
                cam_rmse = float(cam_metrics.get("cam_anchor_rmse"))
            except Exception:
                cam_rmse = None

        objs = cam_fr.get("objects")
        if not isinstance(objs, list):
            continue

        for o in objs:
            if not isinstance(o, dict):
                continue
            oid = o.get("id")
            if oid is None:
                continue

            pw = o.get("pos_world")
            if not isinstance(pw, (list, tuple)) or len(pw) < 2:
                continue

            try:
                x = float(pw[0])
                y = float(pw[1])
            except Exception:
                continue

            extra = o.get("extra")
            rmse = cam_rmse
            if isinstance(extra, dict) and extra.get("cam_anchor_rmse") is not None:
                try:
                    rmse = float(extra.get("cam_anchor_rmse"))
                except Exception:
                    rmse = rmse

            conf = o.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else 1.0
            except Exception:
                conf_f = 1.0

            obs_by_id.setdefault(str(oid), []).append(
                {
                    "x": x,
                    "y": y,
                    "rmse": rmse,
                    "confidence": conf_f,
                }
            )

    return obs_by_id


def _diff_stats(
    cpu: dict[str, Tuple[float, float]],
    gpu: dict[str, Tuple[float, float]],
) -> DiffStats:
    keys = sorted(set(cpu.keys()) | set(gpu.keys()))
    if not keys:
        return DiffStats(samples=0, rmse_cm=0.0, max_abs_diff_cm=0.0)

    se = 0.0
    n = 0
    max_abs = 0.0

    for k in keys:
        if k not in cpu or k not in gpu:
            continue
        cx, cy = cpu[k]
        gx, gy = gpu[k]
        dx = (gx - cx) * 100.0
        dy = (gy - cy) * 100.0
        se += (dx * dx) + (dy * dy)
        n += 1
        max_abs = max(max_abs, abs(dx), abs(dy))

    rmse = math.sqrt(se / float(max(n, 1))) if n else 0.0
    return DiffStats(samples=n, rmse_cm=float(rmse), max_abs_diff_cm=float(max_abs))


def _maybe_gpu_backend(device: int) -> FusionComputeBackend | None:
    try:
        return GpuCupyBackend(device=device)
    except GpuUnavailable:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M9.6: CPU↔GPU compute equivalence for fuse_xy")
    ap.add_argument("--session-jsonl", type=Path, required=True, help="Input session.jsonl")
    ap.add_argument("--out-csv", type=Path, required=True, help="Output CSV (summary row)")
    ap.add_argument("--method", choices=["avg", "weighted"], default="weighted")
    ap.add_argument("--device", type=int, default=0, help="CUDA device index for CuPy")
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all frames")
    ap.add_argument("--tolerance-rmse-cm", type=float, default=0.05)
    ap.add_argument("--tolerance-max-cm", type=float, default=0.20)
    ap.add_argument("--require-gpu", action="store_true", help="Fail if GPU backend unavailable")
    args = ap.parse_args(argv)

    inp = Path(args.session_jsonl)
    if not inp.is_file():
        raise SystemExit(f"session-jsonl not found: {inp}")

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    cpu_backend: FusionComputeBackend = CpuNumpyBackend()
    gpu_backend = _maybe_gpu_backend(int(args.device))

    if gpu_backend is None and args.require_gpu:
        print("[equivalence] ERROR: GPU backend requested but unavailable (CuPy/CUDA not found)")
        return 2

    frames_used = 0
    total_samples = 0
    se_cm2 = 0.0
    max_abs_cm = 0.0

    with inp.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if _is_header_record(obj):
                continue

            obs_by_id = _extract_obs_by_id(obj)
            if not obs_by_id:
                continue

            cpu = cpu_backend.fuse_xy(obs_by_id, method=str(args.method))
            if gpu_backend is None:
                # If GPU unavailable, still write a CSV row with pass=false.
                st = DiffStats(samples=0, rmse_cm=float("nan"), max_abs_diff_cm=float("nan"))
                row = {
                    "session_jsonl": str(inp),
                    "method": str(args.method),
                    "frames_used": 0,
                    "samples": 0,
                    "rmse_diff_cm": st.rmse_cm,
                    "max_abs_diff_cm": st.max_abs_diff_cm,
                    "pass": False,
                    "cpu_backend": cpu_backend.name,
                    "gpu_backend": "(unavailable)",
                    "gpu_device": int(args.device),
                    "note": "GPU backend unavailable (CuPy/CUDA missing)",
                }
                with out_csv.open("w", newline="", encoding="utf-8") as wf:
                    w = csv.DictWriter(wf, fieldnames=list(row.keys()))
                    w.writeheader()
                    w.writerow(row)
                print("[equivalence] GPU backend unavailable; wrote summary CSV")
                return 3

            gpu = gpu_backend.fuse_xy(obs_by_id, method=str(args.method))
            if hasattr(gpu_backend, "synchronize"):
                gpu_backend.synchronize()

            st = _diff_stats(cpu, gpu)
            if st.samples > 0:
                total_samples += st.samples
                se_cm2 += (st.rmse_cm**2) * float(st.samples)
                max_abs_cm = max(max_abs_cm, st.max_abs_diff_cm)

            frames_used += 1
            if args.max_frames and frames_used >= int(args.max_frames):
                break

    if total_samples > 0:
        rmse_cm = math.sqrt(se_cm2 / float(total_samples))
    else:
        rmse_cm = 0.0

    passed = (rmse_cm <= float(args.tolerance_rmse_cm)) and (
        max_abs_cm <= float(args.tolerance_max_cm)
    )

    row = {
        "session_jsonl": str(inp),
        "method": str(args.method),
        "frames_used": int(frames_used),
        "samples": int(total_samples),
        "rmse_diff_cm": float(rmse_cm),
        "max_abs_diff_cm": float(max_abs_cm),
        "pass": bool(passed),
        "cpu_backend": cpu_backend.name,
        "gpu_backend": gpu_backend.name if gpu_backend is not None else "(unavailable)",
        "gpu_device": int(args.device),
        "note": "",
    }

    with out_csv.open("w", newline="", encoding="utf-8") as wf:
        w = csv.DictWriter(wf, fieldnames=list(row.keys()))
        w.writeheader()
        w.writerow(row)

    print("[equivalence] frames_used=", frames_used)
    print("[equivalence] samples=", total_samples)
    print("[equivalence] rmse_diff_cm=", f"{rmse_cm:.6f}")
    print("[equivalence] max_abs_diff_cm=", f"{max_abs_cm:.6f}")
    print("[equivalence] PASS" if passed else "[equivalence] FAIL")
    print("[equivalence] wrote ->", out_csv)

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
