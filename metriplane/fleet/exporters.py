from __future__ import annotations

import logging
from pathlib import Path

from metriplane.fleet.heartbeat import FleetHeartbeat

log = logging.getLogger("metriplane.fleet")


class JsonlHeartbeatExporter:
    """Appends heartbeats to a local JSONL file. Never raises into the caller."""

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, hb: FleetHeartbeat) -> bool:
        try:
            with self.output_path.open("a") as f:
                f.write(hb.to_json() + "\n")
            return True
        except Exception as e:  # pragma: no cover - disk failure
            log.warning("fleet jsonl export failed: %s", e)
            return False

    def close(self) -> None:
        return


class MqttHeartbeatExporter:
    """Optional MQTT exporter. Requires paho-mqtt; degrades gracefully if absent."""

    def __init__(self, broker: str, topic: str, port: int = 1883):
        self.broker = broker
        self.topic = topic
        self.port = port
        self._client = None
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            self._client = mqtt.Client()
            self._client.connect(broker, port, keepalive=30)
        except Exception as e:
            log.warning("MQTT exporter unavailable (%s); heartbeats will be skipped", e)
            self._client = None

    def publish(self, hb: FleetHeartbeat) -> bool:
        if self._client is None:
            return False
        try:
            self._client.publish(self.topic, hb.to_json())
            return True
        except Exception as e:  # pragma: no cover
            log.warning("MQTT publish failed: %s", e)
            return False

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
