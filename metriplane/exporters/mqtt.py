from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("metriplane.exporters")


class MqttExporter:
    """Optional MQTT exporter (requires paho-mqtt). Degrades gracefully if absent."""

    def __init__(self, broker: str, topic_prefix: str = "metriplane", port: int = 1883):
        self.topic_prefix = topic_prefix
        self._client = None
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            self._client = mqtt.Client()
            self._client.connect(broker, port, keepalive=30)
        except Exception as e:
            log.warning("MQTT exporter unavailable (%s); records will be skipped", e)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def _pub(self, suffix: str, payload: dict[str, Any]) -> bool:
        if self._client is None:
            return False
        try:
            self._client.publish(f"{self.topic_prefix}/{suffix}", json.dumps(payload))
            return True
        except Exception as e:  # pragma: no cover
            log.warning("MQTT publish failed: %s", e)
            return False

    def publish_event(self, event: dict[str, Any]) -> bool:
        return self._pub("events", event)

    def publish_frame(self, frame: dict[str, Any]) -> bool:
        return self._pub("frames", frame)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
