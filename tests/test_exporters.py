# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

import pytest

from metriplane.exporters.base import JsonlExporter, MockExporter
from metriplane.exporters.kafka import KafkaExporter
from metriplane.exporters.mqtt import MqttExporter
from metriplane.exporters.parquet import export_run_dir, parquet_available
from metriplane.exporters.webhook import WebhookExporter


def test_mock_exporter_counts():
    e = MockExporter()
    e.publish_event({"a": 1})
    e.publish_frame({"b": 2})
    e.close()
    assert e.events == 1 and e.frames == 1


def test_jsonl_exporter_writes(tmp_path):
    e = JsonlExporter(tmp_path)
    e.publish_event({"rule_id": "r"})
    e.publish_frame({"frame_id": 0})
    e.close()
    events = (tmp_path / "events.jsonl").read_text().strip().splitlines()
    frames = (tmp_path / "frames.jsonl").read_text().strip().splitlines()
    assert json.loads(events[0])["rule_id"] == "r"
    assert json.loads(frames[0])["frame_id"] == 0


def test_webhook_unreachable_returns_false():
    e = WebhookExporter("http://127.0.0.1:0/nope", timeout_s=0.2)
    assert e.publish_event({"x": 1}) is False  # no raise


def test_mqtt_unavailable_graceful():
    e = MqttExporter("localhost", topic_prefix="metriplane")
    # paho-mqtt almost certainly not installed / no broker -> unavailable, no crash
    assert e.publish_event({"x": 1}) in (True, False)
    assert e.available in (True, False)
    e.close()


def test_kafka_unavailable_graceful():
    e = KafkaExporter("localhost:9092")
    assert e.publish_event({"x": 1}) in (True, False)
    e.close()


def test_parquet_availability_flag():
    ok, engine = parquet_available()
    assert isinstance(ok, bool)
    if ok:
        assert engine in ("pyarrow", "fastparquet")


def test_parquet_export_or_clear_error(tmp_path):
    # build a tiny run dir
    run = tmp_path / "run"
    run.mkdir()
    (run / "alerts.jsonl").write_text(
        json.dumps({"rule_id": "r", "severity": "warning", "ts": 1.0}) + "\n"
    )
    ok, _ = parquet_available()
    if ok:
        result = export_run_dir(run)
        assert "alerts.parquet" in result["written"]
    else:
        with pytest.raises(RuntimeError, match="Parquet export needs an engine"):
            export_run_dir(run)


def test_throughput_benchmark_runs(tmp_path):
    from benchmarks.event_throughput import run

    rows = run(2000, tmp_path)
    backends = {r["backend"] for r in rows}
    assert "mock" in backends and "jsonl" in backends
    mock_row = next(r for r in rows if r["backend"] == "mock")
    assert mock_row["events_per_s"] > 0
