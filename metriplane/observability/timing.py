# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import csv
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, ContextManager, Iterable


def _now_ns() -> int:
    # perf_counter_ns = monotonic, high-resolution timing
    return time.perf_counter_ns()


def _env_flag_any(names: list[str], default: str = "0") -> bool:
    """
    Return True if ANY env var in `names` is set to a truthy value.
    """
    for name in names:
        v = os.getenv(name)
        if v is None:
            continue
        s = str(v).strip().lower()
        return s not in ("0", "false", "no", "off", "")
    # If none are set, fall back to default
    s = str(default).strip().lower()
    return s not in ("0", "false", "no", "off", "")


def percentile(values: list[float], p: float) -> float | None:
    """
    Linear-interpolated percentile, like numpy.percentile(..., method="linear").
    values must be a non-empty list.
    """
    if not values:
        return None
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))

    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return float(xs[0])

    # rank in [0, n-1]
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, n - 1)
    if c == f:
        return float(xs[f])
    d0 = xs[f]
    d1 = xs[c]
    return float(d0 + (d1 - d0) * (k - f))


@dataclass(frozen=True, slots=True)
class StageSummary:
    stage: str
    count: int
    mean_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None


class _NoopSpan(ContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Span(ContextManager[None]):
    def __init__(self, timing: "StageTiming", stage: str) -> None:
        self._timing = timing
        self._stage = stage
        self._t0: int | None = None

    def __enter__(self) -> None:
        self._t0 = _now_ns()
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        t0 = self._t0
        if t0 is None:
            return None
        dt = _now_ns() - t0
        self._timing.add_stage_ns(self._stage, dt)
        return None


class StageTiming:
    """
    Stage timing collector with two compatible APIs:

    Legacy API (still supported):
      - timing.span("stage") context manager
      - observe_ns("stage", dt_ns)
      - snapshot() -> p50/p95
      - write_csv(path) -> summary CSV

    M9.5 API (used by run_fusion.py):
      - begin_frame(ts, frame_id)
      - add_stage_ns(stage, dt_ns)
      - stage("stage") context manager (alias of span)
      - end_frame() -> writes per-frame CSV row
      - close() -> writes summary CSV + closes files

    Enable/disable:
      - If enabled is passed, it is authoritative.
      - Otherwise we consider METRIPLANE_TIMING / METRIPLANE_TIMING / METRIPLANE_STAGE_TIMING.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        max_samples_per_stage: int = 200_000,
        stages: Iterable[str] | None = None,
        frames_csv_path: str | Path | None = None,
        summary_csv_path: str | Path | None = None,
        flush_every: int = 250,
        run_id: str | None = None,
        config_hash: str | None = None,
        git_commit: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if enabled is None:
            enabled = _env_flag_any(
                ["METRIPLANE_TIMING", "METRIPLANE_TIMING", "METRIPLANE_STAGE_TIMING"],
                default="0",
            )
        self.enabled = bool(enabled)

        self.max_samples_per_stage = int(max(10, max_samples_per_stage))
        self._lock = Lock()
        self._samples_ms: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.max_samples_per_stage)
        )
        self._started_ns = _now_ns()

        # M9.5 / per-frame config
        self._stages: list[str] = [str(s) for s in (stages or [])]
        self._frames_csv_path: Path | None = Path(frames_csv_path) if frames_csv_path is not None else None
        self._summary_csv_path: Path | None = Path(summary_csv_path) if summary_csv_path is not None else None
        self._flush_every = int(max(1, flush_every))

        self._run_id = run_id
        self._config_hash = config_hash
        self._git_commit = git_commit
        self._extra = dict(extra or {})

        # Per-frame state
        self._frame_active: bool = False
        self._frame_ts: float | None = None
        self._frame_id: int | None = None
        self._frame_stage_ns: dict[str, int] = {}
        self._frames_written: int = 0

        # CSV writer for per-frame
        self._frames_f = None
        self._frames_w = None

        if self.enabled and self._frames_csv_path is not None:
            self._frames_csv_path.parent.mkdir(parents=True, exist_ok=True)
            self._frames_f = self._frames_csv_path.open("w", encoding="utf-8", newline="")
            self._frames_w = csv.writer(self._frames_f)

            if self._stages:
                header = [
                    "run_id",
                    "config_hash",
                    "git_commit",
                    "ts",
                    "frame_id",
                    *[f"stage.{s}_ms" for s in self._stages],
                    "total_ms",
                    "uptime_s",
                ]
            else:
                header = [
                    "run_id",
                    "config_hash",
                    "git_commit",
                    "ts",
                    "frame_id",
                    "stages_json",
                    "total_ms",
                    "uptime_s",
                ]
            self._frames_w.writerow(header)
            self._frames_f.flush()

    # ---------------------------
    # Time helpers
    # ---------------------------

    def now_ns(self) -> int:
        return _now_ns()

    def _uptime_s(self) -> float:
        return float(max(0, self.now_ns() - self._started_ns)) / 1e9

    # ---------------------------
    # Legacy API
    # ---------------------------

    def span(self, stage: str) -> ContextManager[None]:
        if not self.enabled:
            return _NoopSpan()
        return _Span(self, str(stage))

    # Alias used by run_fusion.py
    def stage(self, stage: str) -> ContextManager[None]:
        return self.span(stage)

    def observe_ns(self, stage: str, dt_ns: int) -> None:
        if not self.enabled:
            return
        if dt_ns < 0:
            return
        ms = float(dt_ns) / 1e6
        st = str(stage)
        with self._lock:
            self._samples_ms[st].append(ms)

    def snapshot(self) -> list[StageSummary]:
        if not self.enabled:
            return []

        with self._lock:
            items = {k: list(v) for k, v in self._samples_ms.items()}

        out: list[StageSummary] = []
        for stage, vals in items.items():
            if not vals:
                out.append(StageSummary(stage=stage, count=0, mean_ms=None, p50_ms=None, p95_ms=None, max_ms=None))
                continue

            count = len(vals)
            mean_ms = float(sum(vals)) / float(count) if count > 0 else None
            p50 = percentile(vals, 50.0)
            p95 = percentile(vals, 95.0)
            max_ms = float(max(vals)) if vals else None

            out.append(
                StageSummary(
                    stage=stage,
                    count=count,
                    mean_ms=mean_ms,
                    p50_ms=p50,
                    p95_ms=p95,
                    max_ms=max_ms,
                )
            )

        # Sort by p95 desc (bottlenecks first), then stage name
        def _key(s: StageSummary) -> tuple[float, str]:
            p95 = s.p95_ms if s.p95_ms is not None else -1.0
            return (-float(p95), s.stage)

        out.sort(key=_key)
        return out

    def write_csv(
        self,
        path: str | Path,
        *,
        run_id: str | None = None,
        config_hash: str | None = None,
        git_commit: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Path:
        """
        Write stage summaries to CSV.
        Columns:
          run_id, config_hash, git_commit, stage, count, mean_ms, p50_ms, p95_ms, max_ms, uptime_s
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        uptime_s = self._uptime_s()
        rows = self.snapshot()

        extra = dict(extra or {})
        extra_keys = sorted(extra.keys())

        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            header = [
                "run_id",
                "config_hash",
                "git_commit",
                "stage",
                "count",
                "mean_ms",
                "p50_ms",
                "p95_ms",
                "max_ms",
                "uptime_s",
                *[f"extra.{k}" for k in extra_keys],
            ]
            w.writerow(header)

            for s in rows:
                w.writerow(
                    [
                        run_id or "",
                        config_hash or "",
                        git_commit or "",
                        s.stage,
                        int(s.count),
                        "" if s.mean_ms is None else f"{s.mean_ms:.3f}",
                        "" if s.p50_ms is None else f"{s.p50_ms:.3f}",
                        "" if s.p95_ms is None else f"{s.p95_ms:.3f}",
                        "" if s.max_ms is None else f"{s.max_ms:.3f}",
                        f"{uptime_s:.3f}",
                        *[extra.get(k, "") for k in extra_keys],
                    ]
                )

        return p

    def bottleneck(self) -> StageSummary | None:
        rows = self.snapshot()
        return rows[0] if rows else None

    # ---------------------------
    # M9.5 Per-frame API
    # ---------------------------

    def begin_frame(self, *, ts: float, frame_id: int) -> None:
        if not self.enabled:
            return
        self._frame_active = True
        self._frame_ts = float(ts)
        self._frame_id = int(frame_id)
        self._frame_stage_ns = {}

    def add_stage_ns(self, stage: str, dt_ns: int) -> None:
        """
        Adds a stage duration (ns) to:
          - rolling per-stage samples (for p50/p95)
          - current frame accumulator (for frames CSV)
        """
        if not self.enabled:
            return
        if dt_ns < 0:
            return

        st = str(stage)
        self.observe_ns(st, int(dt_ns))

        if self._frame_active:
            prev = int(self._frame_stage_ns.get(st, 0))
            self._frame_stage_ns[st] = prev + int(dt_ns)

    def end_frame(self) -> None:
        if not self.enabled:
            return

        try:
            if self._frames_w is None or self._frames_f is None:
                return

            ts = self._frame_ts
            fid = self._frame_id
            if ts is None or fid is None:
                return

            stage_ms: dict[str, float] = {k: float(v) / 1e6 for k, v in self._frame_stage_ns.items()}
            total_ms = float(sum(stage_ms.values()))
            uptime_s = self._uptime_s()

            if self._stages:
                row = [
                    self._run_id or "",
                    self._config_hash or "",
                    self._git_commit or "",
                    f"{float(ts):.6f}",
                    int(fid),
                    *[
                        ("" if s not in stage_ms else f"{stage_ms[s]:.3f}")
                        for s in self._stages
                    ],
                    f"{total_ms:.3f}",
                    f"{uptime_s:.3f}",
                ]
            else:
                row = [
                    self._run_id or "",
                    self._config_hash or "",
                    self._git_commit or "",
                    f"{float(ts):.6f}",
                    int(fid),
                    json.dumps(stage_ms, sort_keys=True, separators=(",", ":")),
                    f"{total_ms:.3f}",
                    f"{uptime_s:.3f}",
                ]

            self._frames_w.writerow(row)
            self._frames_written += 1
            if (self._frames_written % self._flush_every) == 0:
                self._frames_f.flush()
        finally:
            self._frame_active = False
            self._frame_ts = None
            self._frame_id = None
            self._frame_stage_ns = {}

    def close(self) -> None:
        """
        Flush per-frame CSV (if enabled) and write summary CSV (if configured).
        Safe to call multiple times.
        """
        if not self.enabled:
            return

        # If a frame is in-progress, try to emit it
        try:
            if self._frame_active:
                self.end_frame()
        except Exception:
            pass

        # Write summary if requested
        if self._summary_csv_path is not None:
            try:
                self.write_csv(
                    self._summary_csv_path,
                    run_id=self._run_id,
                    config_hash=self._config_hash,
                    git_commit=self._git_commit,
                    extra=self._extra,
                )
            except Exception:
                # Don't crash shutdown due to timing
                pass

        # Close frame CSV file
        try:
            if self._frames_f is not None:
                try:
                    self._frames_f.flush()
                except Exception:
                    pass
                self._frames_f.close()
        finally:
            self._frames_f = None
            self._frames_w = None
