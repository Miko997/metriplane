# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("metriplane.exporters")


class WebhookExporter:
    """POSTs events to an HTTP endpoint using stdlib urllib. Fails gracefully."""

    def __init__(self, url: str, timeout_s: float = 2.0):
        self.url = url
        self.timeout_s = timeout_s

    def _post(self, payload: dict[str, Any]) -> bool:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.warning("webhook export failed: %s", e)
            return False

    def publish_event(self, event: dict[str, Any]) -> bool:
        return self._post({"type": "event", "payload": event})

    def publish_frame(self, frame: dict[str, Any]) -> bool:
        return self._post({"type": "frame", "payload": frame})

    def close(self) -> None:
        return
