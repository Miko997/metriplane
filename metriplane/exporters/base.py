from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("metriplane.exporters")


class Exporter(Protocol):
    """Event/frame exporter. Implementations must never raise into the caller."""

    def publish_event(self, event: dict[str, Any]) -> bool: ...
    def publish_frame(self, frame: dict[str, Any]) -> bool: ...
    def close(self) -> None: ...


class JsonlExporter:
    """Appends events/frames to JSONL files. Always available (stdlib)."""

    def __init__(self, out_dir: str | Path, prefix: str = ""):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self._events = (self.out_dir / f"{prefix}events.jsonl").open("a")
        self._frames = (self.out_dir / f"{prefix}frames.jsonl").open("a")

    def publish_event(self, event: dict[str, Any]) -> bool:
        try:
            self._events.write(json.dumps(event, separators=(",", ":")) + "\n")
            return True
        except Exception as e:  # pragma: no cover
            log.warning("jsonl event export failed: %s", e)
            return False

    def publish_frame(self, frame: dict[str, Any]) -> bool:
        try:
            self._frames.write(json.dumps(frame, separators=(",", ":")) + "\n")
            return True
        except Exception as e:  # pragma: no cover
            log.warning("jsonl frame export failed: %s", e)
            return False

    def close(self) -> None:
        for fh in (self._events, self._frames):
            try:
                fh.close()
            except Exception:
                pass


class MockExporter:
    """In-memory exporter for benchmarks/tests. Counts published records."""

    def __init__(self) -> None:
        self.events = 0
        self.frames = 0

    def publish_event(self, event: dict[str, Any]) -> bool:
        self.events += 1
        return True

    def publish_frame(self, frame: dict[str, Any]) -> bool:
        self.frames += 1
        return True

    def close(self) -> None:
        return
