# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

# metriplane/replay/engine.py
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from metriplane.time.clock import FixedStepClock, ReplayClock, ms_to_ns


ClockMode = str  # "replay" | "fixed"


def _decimal_seconds_to_ns(value: Any) -> int:
    """Convert a JSON 'ts' seconds field to integer ns deterministically."""
    try:
        # Use Decimal(str(x)) to avoid float repr surprises.
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"Invalid ts value for seconds->ns conversion: {value!r}")
    return int(d * Decimal("1000000000"))


def _get_record_ts_ns(rec: Dict[str, Any]) -> int:
    # Prefer integer ns if it exists.
    if "ts_ns" in rec and isinstance(rec["ts_ns"], int):
        return int(rec["ts_ns"])
    # Fall back to float seconds.
    if "ts" in rec:
        return _decimal_seconds_to_ns(rec["ts"])
    raise KeyError("Record has no ts_ns or ts field")


def _is_header_record(rec: Dict[str, Any]) -> bool:
    # Future-proof for M9.4 header records.
    t = rec.get("type") or rec.get("record_type")
    return t in {"header", "run_header", "provenance"}


def _stable_sort_frame_inplace(frame: Dict[str, Any]) -> None:
    # R1 stable ordering requirement (objects must be stably sorted). :contentReference[oaicite:3]{index=3}
    objs = frame.get("objects")
    if isinstance(objs, list):
        def key(o: Any) -> str:
            if not isinstance(o, dict):
                return ""
            return str(o.get("id", ""))
        objs.sort(key=key)


@dataclass(frozen=True)
class EngineConfig:
    input_path: Path
    clock: ClockMode = "replay"          # "replay" | "fixed"
    dt_ms: Optional[int] = None          # required if clock="fixed"
    run_id: str = "replay"
    speed: Optional[float] = None        # only used if you implement throttling
    output_max_frames: Optional[int] = None  # helpful for quick debug


def iter_input_frames(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if isinstance(rec, dict) and _is_header_record(rec):
                continue
            if not isinstance(rec, dict):
                continue
            yield rec


def _load_frames_with_rel_ts(path: Path) -> List[Tuple[int, Dict[str, Any]]]:
    frames: List[Tuple[int, Dict[str, Any]]] = []
    ts0: Optional[int] = None

    for rec in iter_input_frames(path):
        ts_ns = _get_record_ts_ns(rec)
        if ts0 is None:
            ts0 = ts_ns
        rel = ts_ns - ts0
        if rel < 0:
            # Defensive: recorded timestamps should be non-decreasing.
            # If they are not, determinism can be compromised.
            raise ValueError(f"Non-monotonic timestamps in input: {path}")
        frames.append((rel, rec))

    if not frames:
        raise ValueError(f"No frames found in input JSONL: {path}")
    return frames


def iter_replay_outputs(cfg: EngineConfig) -> Iterator[Dict[str, Any]]:
    frames = _load_frames_with_rel_ts(cfg.input_path)

    if cfg.clock not in {"replay", "fixed"}:
        raise ValueError(f"Unknown clock mode: {cfg.clock}")

    max_frames = cfg.output_max_frames

    if cfg.clock == "replay":
        clock = ReplayClock(0)
        emitted = 0
        for rel_ts_ns, rec in frames:
            clock.advance_to_ns(rel_ts_ns)
            out = dict(rec)
            out["ts_sim_ns"] = clock.now_ns()
            out["run_id"] = cfg.run_id
            _stable_sort_frame_inplace(out)
            yield out
            emitted += 1
            if max_frames is not None and emitted >= max_frames:
                return
        return

    # fixed-step mode
    if cfg.dt_ms is None:
        raise ValueError("dt_ms is required when clock='fixed'")
    dt_ns = ms_to_ns(cfg.dt_ms)
    clock = FixedStepClock(dt_ns=dt_ns, current_ns=0)

    end_ns = frames[-1][0]
    idx = 0
    last_rec: Optional[Dict[str, Any]] = None
    emitted = 0

    # Emit at ts=0, dt, 2dt, ... until we pass end_ns.
    while True:
        ts_sim_ns = clock.now_ns()

        # Advance idx to include frames <= current tick.
        while idx < len(frames) and frames[idx][0] <= ts_sim_ns:
            last_rec = frames[idx][1]
            idx += 1

        # If tick is before first frame time, pin to first frame.
        if last_rec is None:
            last_rec = frames[0][1]

        out = dict(last_rec)
        out["ts_sim_ns"] = int(ts_sim_ns)
        out["run_id"] = cfg.run_id
        _stable_sort_frame_inplace(out)
        yield out

        emitted += 1
        if max_frames is not None and emitted >= max_frames:
            return

        if ts_sim_ns >= end_ns:
            return

        clock.tick()


def write_outputs_jsonl(out_path: Path, outputs: Iterable[Dict[str, Any]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in outputs:
            # Canonical JSON for byte-stable output across runs.
            line = json.dumps(rec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            f.write(line + "\n")
