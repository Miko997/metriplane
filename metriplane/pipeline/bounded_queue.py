# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""metriplane.pipeline.bounded_queue

A small, dependency-free bounded queue with explicit drop/backpressure policies.

Why not queue.Queue?
- queue.Queue is bounded, but it doesn't expose *policy* (drop oldest vs keep latest)
  as a first-class concept.
- For real-time vision pipelines, "KEEP_LATEST" is often the safest behavior:
  it keeps memory bounded and prevents runaway latency under overload.

Policies implemented (M9.2):
- KEEP_ALL:   bounded, but blocks the producer when full (true backpressure).
- DROP_OLDEST: bounded, keeps newest by evicting the oldest when full.
- KEEP_LATEST: bounded, replaces the entire queue with the newest item.

All policies guarantee: qsize() <= maxsize (if maxsize > 0).

This module is intentionally generic so it can be reused by camera ingest,
WS streaming, analytics export, etc.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from threading import Condition
from typing import Deque, Generic, Iterable, Iterator, Optional, TypeVar

import queue as _queue


T = TypeVar("T")


class QueuePolicy(str, Enum):
    """Overflow policy."""

    # Producer blocks when queue is full.
    KEEP_ALL = "KEEP_ALL"

    # Evict the oldest item to make room for the newest.
    DROP_OLDEST = "DROP_OLDEST"

    # Keep only the newest item (drain/replace).
    KEEP_LATEST = "KEEP_LATEST"


@dataclass(frozen=True, slots=True)
class PutResult:
    """Result of a put() attempt."""

    ok: bool
    dropped: int
    reason: str


class QueueClosed(RuntimeError):
    pass


class BoundedQueue(Generic[T]):
    """A bounded FIFO queue with explicit overflow policy.

    Notes:
    - For KEEP_LATEST we intentionally discard backlog to bound end-to-end latency.
    - For KEEP_ALL the producer blocks when full; this provides backpressure.

    Thread-safety:
    - put()/get()/qsize() are safe across multiple producers/consumers.
    """

    def __init__(
        self,
        *,
        maxsize: int,
        policy: QueuePolicy = QueuePolicy.KEEP_LATEST,
        name: str = "",
    ) -> None:
        if maxsize <= 0:
            raise ValueError("BoundedQueue requires maxsize > 0")
        self._maxsize = int(maxsize)
        self._policy = QueuePolicy(policy)
        self._name = str(name)

        self._cv = Condition()
        self._q: Deque[T] = deque()
        self._closed = False

        # Counters (purely informational)
        self._dropped_total = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def policy(self) -> QueuePolicy:
        return self._policy

    def close(self) -> None:
        """Close the queue.

        - Further put() calls raise QueueClosed.
        - get() will continue draining existing items; once empty, it raises queue.Empty.
        """
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def is_closed(self) -> bool:
        with self._cv:
            return bool(self._closed)

    def dropped_total(self) -> int:
        with self._cv:
            return int(self._dropped_total)

    def qsize(self) -> int:
        with self._cv:
            return len(self._q)

    def empty(self) -> bool:
        return self.qsize() == 0

    def full(self) -> bool:
        with self._cv:
            return len(self._q) >= self._maxsize

    def clear(self) -> int:
        """Remove all items and return the number removed."""
        with self._cv:
            n = len(self._q)
            self._q.clear()
            if n:
                self._cv.notify_all()
            return n

    def put(
        self,
        item: T,
        *,
        block: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> PutResult:
        """Put an item.

        Args:
            block:
                - If None: defaults to True for KEEP_ALL, False otherwise.
                - If True: blocks until there is space (or timeout).
                - If False: applies overflow policy immediately.
            timeout: seconds

        Returns:
            PutResult indicating whether the item was enqueued and how many were dropped.

        Raises:
            QueueClosed if queue is closed.
        """
        if block is None:
            block = self._policy == QueuePolicy.KEEP_ALL

        with self._cv:
            if self._closed:
                raise QueueClosed(f"queue closed: {self._name}")

            # Fast path: space available
            if len(self._q) < self._maxsize:
                self._q.append(item)
                self._cv.notify()
                return PutResult(ok=True, dropped=0, reason="enqueued")

            # Queue is full
            if block:
                # Wait for space
                deadline = None if timeout is None else (time.monotonic() + float(timeout))
                while len(self._q) >= self._maxsize:
                    if self._closed:
                        raise QueueClosed(f"queue closed: {self._name}")
                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return PutResult(ok=False, dropped=0, reason="timeout_full")
                        self._cv.wait(timeout=remaining)
                    else:
                        self._cv.wait()

                self._q.append(item)
                self._cv.notify()
                return PutResult(ok=True, dropped=0, reason="enqueued_after_wait")

            # Non-blocking overflow handling
            dropped = 0

            if self._policy == QueuePolicy.DROP_OLDEST:
                # Evict one oldest and insert
                if self._q:
                    self._q.popleft()
                    dropped = 1
                self._q.append(item)
                self._dropped_total += dropped
                self._cv.notify()
                return PutResult(ok=True, dropped=dropped, reason="drop_oldest")

            if self._policy == QueuePolicy.KEEP_LATEST:
                # Drain queue and keep only newest
                dropped = len(self._q)
                self._q.clear()
                self._q.append(item)
                self._dropped_total += dropped
                self._cv.notify()
                return PutResult(ok=True, dropped=dropped, reason="keep_latest")

            # KEEP_ALL but non-blocking requested: refuse enqueue
            return PutResult(ok=False, dropped=0, reason="full_keep_all")

    def get(self, *, block: bool = True, timeout: Optional[float] = None) -> T:
        """Get an item.

        Raises queue.Empty if no item is available.
        """
        with self._cv:
            if self._q:
                item = self._q.popleft()
                self._cv.notify()
                return item

            if not block:
                raise _queue.Empty

            deadline = None if timeout is None else (time.monotonic() + float(timeout))
            while not self._q:
                # If closed and empty => stop
                if self._closed:
                    raise _queue.Empty

                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise _queue.Empty
                    self._cv.wait(timeout=remaining)
                else:
                    self._cv.wait()

            item = self._q.popleft()
            self._cv.notify()
            return item

    def __iter__(self) -> Iterator[T]:
        """Iterate draining items until closed and empty."""
        while True:
            try:
                yield self.get(block=True, timeout=0.25)
            except _queue.Empty:
                if self.is_closed() and self.empty():
                    return

    def drain(self, *, max_items: Optional[int] = None) -> list[T]:
        """Drain up to max_items items and return them."""
        out: list[T] = []
        with self._cv:
            n = len(self._q) if max_items is None else min(len(self._q), int(max_items))
            for _ in range(n):
                out.append(self._q.popleft())
            if n:
                self._cv.notify_all()
        return out

    def extend(self, items: Iterable[T]) -> PutResult:
        """Convenience: put() multiple items, returning an aggregated PutResult."""
        ok_any = False
        dropped_total = 0
        reasons: list[str] = []
        for it in items:
            r = self.put(it)
            ok_any = ok_any or r.ok
            dropped_total += int(r.dropped)
            reasons.append(r.reason)
        reason = "+".join(reasons[-3:]) if reasons else ""
        return PutResult(ok=ok_any, dropped=dropped_total, reason=reason)
