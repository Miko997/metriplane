# Scalable Event Pipeline

Metriplane can export traces, alerts, incidents, and frames to high-volume sinks for batch
analytics and streaming. Exporters are **optional and fail gracefully** — a missing
dependency or unreachable sink never crashes the tracking pipeline.

## Exporters

| Exporter | Dependency | Purpose |
|---|---|---|
| `JsonlExporter` | stdlib | always-available local JSONL |
| `MockExporter` | stdlib | benchmarks/tests (in-memory counts) |
| `WebhookExporter` | stdlib `urllib` | POST events to an HTTP endpoint |
| `MqttExporter` | `paho-mqtt` (optional) | IoT/edge streams |
| `KafkaExporter` | `confluent-kafka` (optional) | high-volume event streams |
| Parquet | `pyarrow` or `fastparquet` (optional) | batch analytics / data lakes |

Every exporter exposes `publish_event(dict)`, `publish_frame(dict)`, `close()` and returns
`False` (logging a warning) instead of raising on failure.

## Parquet export (post-run)

```bash
python -m metriplane.exporters.parquet --run-dir evidence/incidents/INC-0001
```

Converts the run's JSONL artifacts to `exports/parquet/{frames,alerts,incidents}.parquet`.
If no Parquet engine is installed, it prints an install instruction and exits nonzero —
without affecting any running pipeline.

## Throughput benchmark

```bash
python benchmarks/event_throughput.py --n-events 100000 \
  --out evidence/experiments/scalable_event_pipeline_001.csv
```

Reference run (x86): mock ≈ 7.4M events/s, JSONL ≈ 440k events/s.

## Optional dependencies

Install only what you need:

```bash
pip install pyarrow          # Parquet
pip install paho-mqtt        # MQTT
pip install confluent-kafka  # Kafka/Redpanda
```

## Limitations

- Parquet is a post-run batch conversion (not in the hot path).
- MQTT/Kafka exporters require a reachable broker; without one they no-op and log.
- Pseudonymization/privacy modes are future work.
