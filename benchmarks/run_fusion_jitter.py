# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import numpy as np  # type: ignore
import yaml

from metriplane.recording.jsonl import read_jsonl


def _load_test_points(path: Path) -> dict[str, tuple[float, float]]:
    """
    Accept either:
      points:
        - id: 7
          world_xy: [0.1, 0.2]
    or
      - id: 7
        world_xy: [0.1, 0.2]
    """
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pts = data.get("points") if isinstance(data, dict) else data
    out: dict[str, tuple[float, float]] = {}
    if isinstance(pts, list):
        for p in pts:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            xy = p.get("world_xy")
            if pid is None or not isinstance(xy, (list, tuple)) or len(xy) < 2:
                continue
            out[str(pid)] = (float(xy[0]), float(xy[1]))
    return out


def _jitter_std(ts: np.ndarray, x: np.ndarray, y: np.ndarray) -> float:
    # Fit x=a*t+b, y=c*t+d; jitter = std of residual distance
    if len(ts) < 5:
        return float("nan")
    A = np.vstack([ts, np.ones_like(ts)]).T

    ax, bx = np.linalg.lstsq(A, x, rcond=None)[0]
    ay, by = np.linalg.lstsq(A, y, rcond=None)[0]

    xhat = A @ np.array([ax, bx])
    yhat = A @ np.array([ay, by])

    r = np.sqrt((x - xhat) ** 2 + (y - yhat) ** 2)
    return float(np.std(r))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fusion jitter + coverage benchmark (JSONL).")
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--out", type=Path, default=Path("evidence/experiments/fusion_jitter_001.csv"))
    ap.add_argument("--test-points", type=Path, default=None, help="Optional YAML with expected world points by id")
    args = ap.parse_args()

    frames = read_jsonl(args.jsonl)
    if not frames:
        raise SystemExit("no frames found")

    test_pts = _load_test_points(args.test_points) if args.test_points else {}

    # Collect per-object sequences from fused output (=objects)
    per: dict[str, list[tuple[float, float, float]]] = {}  # oid -> [(t,x,y)]
    max_err: dict[str, float] = {}

    for fr in frames:
        t = float(fr.ts)
        for obj in fr.objects:
            if not obj.pos_world:
                continue
            oid = str(obj.id)
            x, y = float(obj.pos_world[0]), float(obj.pos_world[1])
            per.setdefault(oid, []).append((t, x, y))

            if oid in test_pts:
                ex, ey = test_pts[oid]
                e = float(np.hypot(x - ex, y - ey))
                max_err[oid] = max(max_err.get(oid, 0.0), e)

    total_frames = len(frames)

    rows: list[dict[str, Any]] = []
    for oid, seq in sorted(per.items(), key=lambda kv: kv[0]):
        ts = np.array([s[0] for s in seq], dtype=np.float64)
        xs = np.array([s[1] for s in seq], dtype=np.float64)
        ys = np.array([s[2] for s in seq], dtype=np.float64)

        coverage = 100.0 * (len(seq) / float(total_frames))
        jitter = _jitter_std(ts, xs, ys)

        rows.append(
            {
                "object_id": oid,
                "frames_seen": len(seq),
                "frames_total": total_frames,
                "coverage_pct": coverage,
                "jitter_std_m": jitter,
                "max_error_m": max_err.get(oid, float("nan")) if test_pts else float("nan"),
            }
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["object_id"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print("[fusion_jitter] wrote", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
