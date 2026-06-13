# Scalable Event Pipeline — Phase 15 Evidence

- phase: 15
- feature: scalable_event_pipeline
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/exporters/

## Commands run

```bash
python -m pytest tests/test_exporters.py -q

python benchmarks/event_throughput.py --n-events 100000 \
  --out evidence/experiments/scalable_event_pipeline_001.csv

python -m metriplane.exporters.parquet --run-dir <run_dir>   # needs pyarrow/fastparquet
```

## Throughput result (x86 reference)

| backend | n_events | events/s | p50_publish_ms |
|---|---|---|---|
| mock | 100000 | ~7,400,000 | ~0.00007 |
| jsonl | 100000 | ~441,000 | ~0.0021 |

## Exporters

- JsonlExporter (always available), MockExporter (benchmark)
- WebhookExporter (stdlib urllib; returns False on unreachable endpoint)
- MqttExporter (optional paho-mqtt), KafkaExporter (optional confluent-kafka)
- Parquet post-run conversion (optional pyarrow/fastparquet)

On this host pyarrow is not installed, so Parquet export reports a clear install
instruction and exits nonzero — verified to fail gracefully, never crashing the pipeline.

## Tests

- tests/test_exporters.py (8): mock counts, JSONL write, webhook-unreachable safe,
  MQTT/Kafka graceful-without-deps, Parquet availability + export-or-clear-error, throughput
  benchmark.

## Limitations

- Parquet is a post-run batch conversion; not in the real-time path.
- MQTT/Kafka require a reachable broker; otherwise they no-op and log a warning.
- Optional deps are not core requirements.
