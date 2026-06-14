# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

"""Pipeline utilities (M9.2).

This module is intentionally small and dependency-free.

Key pieces:
- BoundedQueue: bounded queue with explicit drop/backpressure policies.
- StageWorker / ThreadedRuntime: simple threaded stage runner with timing + metrics hooks.
"""

from .bounded_queue import BoundedQueue, PutResult, QueueClosed, QueuePolicy
from .runtime_threaded import StageStats, StageWorker, ThreadedRuntime

__all__ = [
    "BoundedQueue",
    "PutResult",
    "QueueClosed",
    "QueuePolicy",
    "StageStats",
    "StageWorker",
    "ThreadedRuntime",
]
