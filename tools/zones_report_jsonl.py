# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterator

import yaml

from metriplane.schema import ObjectStateModel
from metriplane.zone_analytics import ZoneAnalytics
from metriplane.zones import load_zones

# Keep the "strict" reader as a first attempt (if it works).
from metriplane.recording.jsonl import read_jsonl  # type: ignore


def _repo_root() -> Path:
    # tools/ is directly under metriplane-core/
    return Path(__file__).resolve().parents[1]


def _load_active_profile(calib_dir: Path) -> str | None:
    ap = calib_dir / "active_profile.yaml"
    if not ap.is_file():
        return None
    data: dict[str, Any] = yaml.safe_load(ap.read_text(encoding="utf-8")) or {}
    prof = data.get("profile")
    if not prof:
        return None
    return str(prof).strip() or None


def _resolve_zones_path(
    *, repo_root: Path, profile: str | None, zones_arg: Path | None
) -> tuple[Path, str | None]:
    """
    Returns: (zones_path, resolved_profile_name_or_none)

    Priority:
      1) explicit --zones
      2) zones.yaml from --profile
      3) zones.yaml from calib/active_profile.yaml
    """
    if zones_arg is not None:
        return zones_arg, None

    calib_dir = repo_root / "calib"
    prof = profile or _load_active_profile(calib_dir)
    if not prof:
        raise SystemExit(
            "[zones_report] ERROR: No --zones provided and no active profile found.\n"
            "Provide either:\n"
            "  --zones calib/profiles/<profile>/zones.yaml\n"
            "or set calib/active_profile.yaml\n"
            "or pass --profile <profile>."
        )

    zones_path = calib_dir / "profiles" / prof / "zones.yaml"
    if not zones_path.is_file():
        raise SystemExit(
            f"[zones_report] ERROR: zones.yaml not found for profile '{prof}': {zones_path}"
        )

    return zones_path, prof


def _file_stats(path: Path) -> tuple[int, int]:
    """(bytes, nonempty_lines)"""
    try:
        size = path.stat().st_size
    except Exception:
        size = -1
    nonempty = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    nonempty += 1
    except Exception:
        nonempty = -1
    return size, nonempty


def _iter_frames_loose(
    jsonl_path: Path,
) -> tuple[Iterator[tuple[float, list[ObjectStateModel]]], dict[str, int]]:
    """
    Loose JSONL reader:
      - parses each line via json.loads
      - extracts ts + objects
      - builds ObjectStateModel list (only id + pos_world + extra)
    Returns (iterator, stats dict).
    """
    stats = {
        "lines_total": 0,
        "lines_nonempty": 0,
        "lines_json_ok": 0,
        "lines_json_bad": 0,
        "lines_missing_ts": 0,
        "frames_yielded": 0,
    }

    def gen() -> Iterator[tuple[float, list[ObjectStateModel]]]:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stats["lines_total"] += 1
                s = line.strip()
                if not s:
                    continue
                stats["lines_nonempty"] += 1

                try:
                    d = json.loads(s)
                    stats["lines_json_ok"] += 1
                except Exception:
                    stats["lines_json_bad"] += 1
                    continue

                if not isinstance(d, dict):
                    stats["lines_missing_ts"] += 1
                    continue

                ts = d.get("ts")
                if ts is None:
                    # Sometimes people use "timestamp" in other tools; accept it defensively.
                    ts = d.get("timestamp")

                try:
                    ts_f = float(ts)
                except Exception:
                    stats["lines_missing_ts"] += 1
                    continue

                objs_raw = d.get("objects") or []
                objs: list[ObjectStateModel] = []

                if isinstance(objs_raw, list):
                    for o in objs_raw:
                        if not isinstance(o, dict):
                            continue
                        oid = o.get("id")
                        if oid is None:
                            continue

                        pos = o.get("pos_world")
                        pos_world = None
                        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                            try:
                                x = float(pos[0])
                                y = float(pos[1])
                                z = float(pos[2]) if len(pos) >= 3 else 0.0
                                pos_world = (x, y, z)
                            except Exception:
                                pos_world = None

                        extra = o.get("extra")
                        # NOTE: ObjectStateModel tolerates extra fields depending on your schema config.
                        objs.append(ObjectStateModel(id=str(oid), pos_world=pos_world, extra=extra))

                stats["frames_yielded"] += 1
                yield (ts_f, objs)

    return gen(), stats


def main() -> int:
    ap = argparse.ArgumentParser(
        description="M6: compute zone dwell/transitions from a recorded Metriplane JSONL."
    )
    ap.add_argument("jsonl", type=Path, help="Recorded session JSONL")

    ap.add_argument(
        "--profile",
        default=None,
        help="Calibration profile name (defaults to calib/active_profile.yaml).",
    )
    ap.add_argument(
        "--zones",
        type=Path,
        default=None,
        help="zones.yaml/json (world coords). Overrides --profile.",
    )

    ap.add_argument("--out", type=Path, default=Path("evidence/analytics/offline_report"))
    ap.add_argument("--prefix", default="m6_offline")
    args = ap.parse_args()

    repo_root = _repo_root()

    # Resolve paths robustly
    jsonl_path = args.jsonl
    if not jsonl_path.is_file():
        candidate = repo_root / jsonl_path
        if candidate.is_file():
            jsonl_path = candidate

    zones_path, resolved_profile = _resolve_zones_path(
        repo_root=repo_root,
        profile=str(args.profile).strip() if args.profile else None,
        zones_arg=args.zones,
    )

    out_dir = args.out
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir

    size_b, nonempty_lines = _file_stats(jsonl_path)

    print(f"[zones_report] jsonl={jsonl_path} (bytes={size_b} nonempty_lines={nonempty_lines})")
    if resolved_profile:
        print(f"[zones_report] profile={resolved_profile}")
    print(f"[zones_report] zones={zones_path}")
    print(f"[zones_report] out={out_dir} prefix={args.prefix}")

    z = load_zones(zones_path)
    a = ZoneAnalytics(z)

    # 1) Try strict reader first (your existing pipeline)
    frames = []
    try:
        frames = read_jsonl(jsonl_path)
    except Exception as e:
        print(f"[zones_report] strict read_jsonl FAILED: {e}")
        frames = []

    if frames:
        print(f"[zones_report] strict reader: OK frames={len(frames)}")
        last_ts = float(frames[0].ts)
        for fr in frames:
            last_ts = float(fr.ts)
            a.update(float(fr.ts), list(fr.objects))
        a.finalize(last_ts)
        paths = a.export_csv(out_dir, prefix=str(args.prefix))
        print("[zones_report] wrote:")
        for k, p in paths.items():
            print(" ", k, "->", p)
        return 0

    # 2) Fallback: loose JSONL parse
    print("[zones_report] strict reader returned 0 frames; trying loose JSONL parse...")
    it, stats = _iter_frames_loose(jsonl_path)

    last_ts: float | None = None
    yielded = 0
    for ts_f, objs in it:
        yielded += 1
        last_ts = ts_f
        a.update(ts_f, objs)

    print("[zones_report] loose stats:", stats)

    if yielded == 0 or last_ts is None:
        print("[zones_report] no frames found (strict=0, loose=0).")
        print(
            "[zones_report] ACTION: open the JSONL and confirm it contains JSON objects per line."
        )
        print(f"[zones_report] HINT: head -n 2 {jsonl_path}")
        return 2

    a.finalize(last_ts)
    paths = a.export_csv(out_dir, prefix=str(args.prefix))
    print("[zones_report] wrote:")
    for k, p in paths.items():
        print(" ", k, "->", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
