# Docker proof — rerun_20260513_160010

Date: 2026-05-13T16:36:10+03:00
Git commit: 382be2dff875cba78f028ea2240f1acf99699e1e

## Health
{"components": {"camera": {"details": {"mode": "dummy"}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173122773605160, "name": "camera", "status": "OK"}, "mapping": {"details": {"enabled": true, "units": "meters"}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173122772922438, "name": "mapping", "status": "OK"}, "recording.jsonl": {"details": {"enabled": true, "mirror_enabled": true, "paths": ["/data/runs/run_20260513_133605Z_6eebf2/session.jsonl", "/data/evidence/sessions/docker_dummy.jsonl"]}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173122765260027, "name": "recording.jsonl", "status": "OK"}, "timing": {"details": {"enabled": false, "frames_csv": "/data/runs/run_20260513_133605Z_6eebf2/latency_frames.csv", "summary_csv": "/data/runs/run_20260513_133605Z_6eebf2/latency_summary.csv"}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173122765275847, "name": "timing", "status": "OK"}, "ws": {"details": {"ws_url": "ws://0.0.0.0:8765"}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173127020264971, "name": "ws", "status": "OK"}, "zones": {"details": {"enabled": true, "units": "meters"}, "last_error": null, "last_error_ts_ns": null, "last_ok_ts_ns": 173122773591474, "name": "zones", "status": "OK"}}, "enabled": true, "overall": "OK", "ts_ns": 173127052730177, "uptime_s": 4.287481792}
## WebSocket smoke
[ws_smoke] OK messages=3 first_frame_id=131 keys=['config_hash', 'events', 'frame_id', 'fused', 'git_commit', 'metrics', 'objects', 'raw_per_camera', 'run_id', 'schema_version', 'source_backend', 'ts', 'ts_sim_ns']
