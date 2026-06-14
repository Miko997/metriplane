# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""metriplane.pipeline.runtime_threaded

A small threaded pipeline runner using :class:`~metriplane.pipeline.bounded_queue.BoundedQueue`.

Design goals (M9.2):
- Each stage has a bounded input queue.
- Under overload, queues remain bounded and the system keeps running.
- Drops are intentional/visible via counters.
- Stage timing is instrumented (simple latency gauges).

This module is intentionally generic so it can be used for:
- camera -> detect -> tracking -> zones -> ws publish
- replay -> analysis
- synthetic benchmarks (see benchmarks/run_backpressure.py)
"""

from __future__ import annotations

import logging
import threading
import time
from metriplane.pipeline.bounded_queue import QueuePolicy
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from metriplane.pipeline.bounded_queue import BoundedQueue, PutResult

try:
    # Optional; keep module usable without the rest of the package in unit tests.
    from metriplane.metrics import MetricsRegistry
except Exception:  # pragma: no cover
    MetricsRegistry = None  # type: ignore

log = logging.getLogger("metriplane.pipeline.runtime_threaded")


@dataclass
class StageStats:
    """Live stats for a stage worker."""

    processed: int = 0
    out_dropped: int = 0
    exceptions: int = 0

    # Last observed per-item processing time (ms)
    last_latency_ms: float = 0.0

    # Simple EWMA for dashboards
    ema_latency_ms: float = 0.0

    # Thread state
    alive: bool = False


def _as_iterable(out: Any) -> Iterable[Any]:
    """Normalize stage output to an iterable of 0..N items."""
    if out is None:
        return ()
    if isinstance(out, (list, tuple)):
        return out
    return (out,)


class StageWorker:
    """A single pipeline stage running in its own thread.

    Parameters
    ----------
    name:
        Stage name (used for logging and metrics labels).

    fn:
        Function applied to each input item.
        Signature: ``fn(item) -> None | item | list[item]``

    in_queue:
        Source queue to consume from.

    out_queue:
        Destination queue to publish to. If None, this is a terminal stage.

    metrics:
        Optional :class:`metriplane.metrics.MetricsRegistry` used to expose:
        - queue depths
        - dropped counters
        - stage latency gauges
    """

    def __init__(
        self,
        *,
        name: str,
        fn: Callable[[Any], Any],
        in_queue: BoundedQueue[Any],
        out_queue: Optional[BoundedQueue[Any]] = None,
        metrics: Optional["MetricsRegistry"] = None,
        poll_s: float = 0.05,
    ) -> None:
        self.name = str(name)
        self.fn = fn
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.metrics = metrics
        self.poll_s = float(poll_s)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"vt-stage-{self.name}", daemon=True)

        self.stats = StageStats()

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    # -----------------------------
    # Worker loop
    # -----------------------------

    def _run(self) -> None:  # pragma: no cover (exercised via benchmark)
        self.stats.alive = True
        try:
            while True:
                if self._stop.is_set() and self.in_queue.empty():
                    break

                try:
                    item = self.in_queue.get(timeout=self.poll_s)
                except Exception:
                    # queue.Empty or timeout
                    continue

                if self.metrics is not None:
                    try:
                        self.metrics.set_queue_depth(self.in_queue.name, self.in_queue.qsize())
                        if self.out_queue is not None:
                            self.metrics.set_queue_depth(self.out_queue.name, self.out_queue.qsize())
                    except Exception:
                        pass

                t0 = time.perf_counter()
                try:
                    out = self.fn(item)
                except Exception:
                    self.stats.exceptions += 1
                    log.exception("stage '%s' exception", self.name)
                    continue
                finally:
                    dt_ms = (time.perf_counter() - t0) * 1000.0
                    self.stats.last_latency_ms = float(dt_ms)
                    # EWMA
                    alpha = 0.2
                    if self.stats.processed <= 0:
                        self.stats.ema_latency_ms = float(dt_ms)
                    else:
                        self.stats.ema_latency_ms = (1.0 - alpha) * float(self.stats.ema_latency_ms) + alpha * float(dt_ms)

                    if self.metrics is not None:
                        try:
                            self.metrics.observe_stage_latency_ms(self.name, float(dt_ms), ema=float(self.stats.ema_latency_ms))
                        except Exception:
                            pass

                # Publish outputs
                if self.out_queue is not None:
                    for o in _as_iterable(out):
                        res: PutResult = self.out_queue.put(o)
                        if res.dropped:
                            self.stats.out_dropped += int(res.dropped)
                            if self.metrics is not None:
                                try:
                                    # PutResult doesn't carry policy; use the queue's configured policy.
                                    pol = self.out_queue.policy.value if hasattr(self.out_queue.policy, "value") else str(self.out_queue.policy)
                                    self.metrics.inc_queue_dropped(self.out_queue.name, policy=str(pol), n=int(res.dropped))
                                except Exception:
                                    pass

                self.stats.processed += 1

        finally:
            self.stats.alive = False


class ThreadedRuntime:
    """A minimal multi-stage threaded runtime.

    This is intentionally "plumbing" only: it does not know about frames, cameras,
    or websockets. It is used by benchmarks and can be integrated into the live
    pipeline incrementally.
    """

    def __init__(self, *, metrics: Optional["MetricsRegistry"] = None) -> None:
        self.metrics = metrics
        self.stages: list[StageWorker] = []

    def add_stage(
        self,
        *,
        name: str,
        fn: Callable[[Any], Any],
        in_queue: BoundedQueue[Any],
        out_queue: Optional[BoundedQueue[Any]] = None,
    ) -> StageWorker:
        st = StageWorker(name=name, fn=fn, in_queue=in_queue, out_queue=out_queue, metrics=self.metrics)
        self.stages.append(st)
        return st

    def start(self) -> None:
        for st in self.stages:
            st.start()

    def stop(self) -> None:
        for st in self.stages:
            st.stop()

    def join(self, timeout: float | None = None) -> None:
        for st in self.stages:
            st.join(timeout=timeout)

    def stats_snapshot(self) -> dict[str, StageStats]:
        return {st.name: st.stats for st in self.stages}
