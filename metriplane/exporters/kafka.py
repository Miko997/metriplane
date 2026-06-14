# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("metriplane.exporters")


class KafkaExporter:
    """Optional Kafka/Redpanda exporter (requires confluent-kafka). Fails gracefully."""

    def __init__(self, bootstrap_servers: str, topic: str = "metriplane-events"):
        self.topic = topic
        self._producer = None
        try:
            from confluent_kafka import Producer  # type: ignore
            self._producer = Producer({"bootstrap.servers": bootstrap_servers})
        except Exception as e:
            log.warning("Kafka exporter unavailable (%s); records will be skipped", e)
            self._producer = None

    @property
    def available(self) -> bool:
        return self._producer is not None

    def _produce(self, payload: dict[str, Any]) -> bool:
        if self._producer is None:
            return False
        try:
            self._producer.produce(self.topic, json.dumps(payload).encode("utf-8"))
            return True
        except Exception as e:  # pragma: no cover
            log.warning("Kafka produce failed: %s", e)
            return False

    def publish_event(self, event: dict[str, Any]) -> bool:
        return self._produce(event)

    def publish_frame(self, frame: dict[str, Any]) -> bool:
        return self._produce(frame)

    def close(self) -> None:
        if self._producer is not None:
            try:
                self._producer.flush(2.0)
            except Exception:
                pass
