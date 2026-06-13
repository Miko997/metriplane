# Fleet Edge Ops

For multi-node deployments, each Metriplane node can emit periodic **heartbeats** carrying
its identity, provenance, health, and basic metrics. A fleet controller (or a log
collector) aggregates these to monitor many camera nodes.

## Heartbeat

```json
{
  "node_id": "cam_node_01",
  "ts": 1718200000.0,
  "run_id": "fleet_test",
  "git_commit": "abc123",
  "config_hash": "def456",
  "health_overall": "OK",
  "fps": 30.0,
  "objects_tracked": 3,
  "active_incidents": 1,
  "frames_total": 100,
  "frames_dropped_total": 0
}
```

## Config

```yaml
fleet:
  enabled: true
  node_id: cam_node_01
  heartbeat_interval_s: 5
  output_file: fleet_heartbeat.jsonl
```

When enabled in a Sentinel run, a heartbeat is written to
`<run-dir>/fleet_heartbeat.jsonl` at shutdown. For continuous operation, the `FleetAgent`
runs a background thread emitting at `heartbeat_interval_s`.

## Agent

`metriplane.fleet.FleetAgent` decouples from runtime internals via a single
`metrics_provider` callback returning a dict. Heartbeat emission never raises into the
runtime — failures are caught and logged.

```python
from metriplane.fleet.agent import FleetAgent, FleetAgentConfig

agent = FleetAgent(
    FleetAgentConfig(node_id="cam_node_01", output_path="runs/r1/fleet_heartbeat.jsonl",
                     run_id="r1", git_commit="abc123"),
    metrics_provider=lambda: {"health_overall": "OK", "fps": 30.0})
agent.start()   # background thread
...
agent.stop()    # joins and closes exporter
```

## Exporters

- **JSONL** (default): appends heartbeats to a local file.
- **MQTT** (optional): requires `paho-mqtt`; degrades gracefully if absent.
- HTTP webhook / AWS IoT: future exporters following the same interface.

## Limitations

- MVP exports local JSONL (and optional MQTT). A central fleet dashboard is future work.
- `fps`/`frames_*` are populated from whatever the metrics provider supplies; the Sentinel
  integration currently reports health, objects, and active incidents.
