# Fleet Edge Ops — Phase 14 Evidence

- phase: 14
- feature: fleet_edge_ops
- git_commit: e13ba72 (uncommitted working tree on harden-external-validation-v014)
- package: metriplane/fleet/

## Commands run

```bash
python -m pytest tests/test_fleet_agent.py -q

# via Sentinel run (fleet block in config):
metriplane sentinel run --config <cfg-with-fleet> --run-id fleet_test --runs-dir <dir>
cat <dir>/fleet_test/fleet_heartbeat.jsonl
```

## Result

```json
{"node_id":"cam_node_01","run_id":"fleet_test","health_overall":"OK",
 "objects_tracked":3,"active_incidents":2,"fps":null,...}
```

The heartbeat includes node id, run id, git commit / config hash (when supplied), health,
and basic metrics. A `FleetAgent` background thread emits at `heartbeat_interval_s`; the
Sentinel runtime emits one heartbeat at shutdown when `fleet.enabled` is set.

## Tests

- tests/test_fleet_agent.py (7): serialization, emit_once JSONL, provenance fields,
  metrics-provider failure safety, start/stop loop, from_config_dict enabled/disabled.

## Limitations

- MVP emits local JSONL (+ optional MQTT exporter that degrades gracefully without
  paho-mqtt). Central fleet aggregation/dashboard is future work.
- `fps`/`frames_*` depend on the metrics provider; the Sentinel integration reports health,
  objects tracked, and active incidents.
