<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Functionality Inventory

Generated deterministically by `python tools/audit_ui_functionality.py --write`.

Canonical projection SHA-256: `62aa35d4976c9e8027b547399f97acd7aa375503a9bca1de41361e3eab6f5d7b`

This is a static source census. It does not characterize runtime behavior or expand browser, platform, environment, or integration support.

## Counts

| surface | count |
| --- | --- |
| actions | 157 |
| HTTP routes | 34 |
| pages | 12 |
| services | 4 |
| topics | 3 |
| baseline route crosswalk | 48 |

## Governed HTTP Routes

| action_id | method | path | source |
| --- | --- | --- | --- |
| api.operator.get.camera_trust | GET | /operator/camera-trust | metriplane/runner/operator_api.py:351 |
| api.operator.get.cameras | GET | /operator/cameras | metriplane/runner/operator_api.py:332 |
| api.operator.get.configs | GET | /operator/configs | metriplane/runner/operator_api.py:336 |
| api.operator.get.env | GET | /operator/env | metriplane/runner/operator_api.py:330 |
| api.operator.get.frames | GET | /operator/frames | metriplane/runner/operator_api.py:353 |
| api.operator.get.incidents | GET | /operator/incidents | metriplane/runner/operator_api.py:347 |
| api.operator.get.latest_run | GET | /operator/latest-run | metriplane/runner/operator_api.py:338 |
| api.operator.get.live_summary | GET | /operator/live-summary | metriplane/runner/operator_api.py:343 |
| api.operator.get.objects | GET | /operator/objects | metriplane/runner/operator_api.py:345 |
| api.operator.get.profiles | GET | /operator/profiles | metriplane/runner/operator_api.py:334 |
| api.operator.get.runner_status | GET | /operator/runner-status | metriplane/runner/operator_api.py:340 |
| api.operator.get.traces | GET | /operator/traces | metriplane/runner/operator_api.py:349 |
| api.operator.post.ask | POST | /operator/ask | metriplane/runner/operator_api.py:386 |
| api.operator.post.calibrate | POST | /operator/calibrate | metriplane/runner/operator_api.py:364 |
| api.operator.post.camera_trust | POST | /operator/camera-trust | metriplane/runner/operator_api.py:382 |
| api.operator.post.checksum | POST | /operator/checksum | metriplane/runner/operator_api.py:372 |
| api.operator.post.create_profile | POST | /operator/create-profile | metriplane/runner/operator_api.py:356 |
| api.operator.post.frames | POST | /operator/frames | metriplane/runner/operator_api.py:384 |
| api.operator.post.generate_report | POST | /operator/generate-report | metriplane/runner/operator_api.py:370 |
| api.operator.post.incidents | POST | /operator/incidents | metriplane/runner/operator_api.py:378 |
| api.operator.post.live_summary | POST | /operator/live-summary | metriplane/runner/operator_api.py:374 |
| api.operator.post.objects | POST | /operator/objects | metriplane/runner/operator_api.py:376 |
| api.operator.post.save_config | POST | /operator/save-config | metriplane/runner/operator_api.py:360 |
| api.operator.post.start_fusion | POST | /operator/start-fusion | metriplane/runner/operator_api.py:362 |
| api.operator.post.traces | POST | /operator/traces | metriplane/runner/operator_api.py:380 |
| api.operator.post.validate_alignment | POST | /operator/validate-alignment | metriplane/runner/operator_api.py:366 |
| api.operator.post.validate_alignment_full | POST | /operator/validate-alignment-full | metriplane/runner/operator_api.py:368 |
| api.operator.post.write_zones | POST | /operator/write-zones | metriplane/runner/operator_api.py:358 |
| api.runner.cancel_job | POST | /jobs/{job_id}/cancel | metriplane/runner/service.py:253 |
| api.runner.commands | GET | /commands | metriplane/runner/service.py:216 |
| api.runner.execute | POST | /execute | metriplane/runner/service.py:251 |
| api.runner.job_detail | GET | /jobs/{job_id} | metriplane/runner/service.py:221 |
| api.runner.jobs | GET | /jobs | metriplane/runner/service.py:218 |
| api.runner.status | GET | /status | metriplane/runner/service.py:214 |

## Local Services

| id | name | protocol | source |
| --- | --- | --- | --- |
| MP2-012.UI.SERVICE.DASHBOARD_STATIC_HTTP | Dashboard static HTTP | http | metriplane/_local_http.py:33 |
| MP2-012.UI.SERVICE.LOCAL_RUNNER_HTTP | Local runner HTTP | http | metriplane/runner/service.py:477 |
| MP2-012.UI.SERVICE.RUNTIME_FRAME_WEBSOCKET | Runtime frame WebSocket | websocket | metriplane/streaming/ws_server.py:49 |
| MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP | Runtime health and metrics HTTP | http | metriplane/metrics.py:314 |

## ROS 2 Topics

| id | topic | parameter | source |
| --- | --- | --- | --- |
| MP2-012.UI.TOPIC.METRIPLANE_ALERTS | /metriplane/alerts | alerts_topic | integrations/ros2/metriplane_ros/launch/bridge.launch.py:15 |
| MP2-012.UI.TOPIC.METRIPLANE_FRAME_STATE | /metriplane/frame_state | frame_topic | integrations/ros2/metriplane_ros/launch/bridge.launch.py:14 |
| MP2-012.UI.TOPIC.METRIPLANE_INCIDENTS | /metriplane/incidents | incidents_topic | integrations/ros2/metriplane_ros/launch/bridge.launch.py:16 |

## Dashboard Pages

| id | page | route | source |
| --- | --- | --- | --- |
| MP2-012.UI.PAGE.ATLAS_HTML | atlas.html | /web/dashboard/atlas.html | web/dashboard/atlas.html |
| MP2-012.UI.PAGE.BENCHMARKS_HTML | benchmarks.html | /web/dashboard/benchmarks.html | web/dashboard/benchmarks.html |
| MP2-012.UI.PAGE.COMMAND_CENTER_HTML | command_center.html | /web/dashboard/command_center.html | web/dashboard/command_center.html |
| MP2-012.UI.PAGE.COMMAND_CENTER_LIVE_HTML | command_center_live.html | /web/dashboard/command_center_live.html | web/dashboard/command_center_live.html |
| MP2-012.UI.PAGE.HELP_HTML | help.html | /web/dashboard/help.html | web/dashboard/help.html |
| MP2-012.UI.PAGE.INDEX_HTML | index.html | /web/dashboard/index.html | web/dashboard/index.html |
| MP2-012.UI.PAGE.INTEGRATIONS_HTML | integrations.html | /web/dashboard/integrations.html | web/dashboard/integrations.html |
| MP2-012.UI.PAGE.OPERATOR_HTML | operator.html | /web/dashboard/operator.html | web/dashboard/operator.html |
| MP2-012.UI.PAGE.REPORT_HTML | report.html | /web/dashboard/report.html | web/dashboard/report.html |
| MP2-012.UI.PAGE.RUN_HTML | run.html | /web/dashboard/run.html | web/dashboard/run.html |
| MP2-012.UI.PAGE.RUNTIME_HTML | runtime.html | /web/dashboard/runtime.html | web/dashboard/runtime.html |
| MP2-012.UI.PAGE.SETTINGS_HTML | settings.html | /web/dashboard/settings.html | web/dashboard/settings.html |

## Frozen Route Crosswalk

| protocol | method | path | relation | target_id |
| --- | --- | --- | --- | --- |
| http | GET | /commands | direct_route | api.runner.commands |
| http | POST | /execute | direct_route | api.runner.execute |
| http | GET | /health | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /health | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /health/ | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /health/ | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /jobs | direct_route | api.runner.jobs |
| http | GET | /jobs/{job_id} | direct_route | api.runner.job_detail |
| http | POST | /jobs/{job_id}/cancel | direct_route | api.runner.cancel_job |
| http | GET | /metrics | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /metrics | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /metrics/ | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | GET | /metrics/ | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | POST | /operator/ask | direct_route | api.operator.post.ask |
| http | POST | /operator/calibrate | direct_route | api.operator.post.calibrate |
| http | GET | /operator/camera-trust | direct_route | api.operator.get.camera_trust |
| http | POST | /operator/camera-trust | direct_route | api.operator.post.camera_trust |
| http | GET | /operator/cameras | direct_route | api.operator.get.cameras |
| http | POST | /operator/checksum | direct_route | api.operator.post.checksum |
| http | GET | /operator/configs | direct_route | api.operator.get.configs |
| http | POST | /operator/create-profile | direct_route | api.operator.post.create_profile |
| http | GET | /operator/env | direct_route | api.operator.get.env |
| http | GET | /operator/frames | direct_route | api.operator.get.frames |
| http | POST | /operator/frames | direct_route | api.operator.post.frames |
| http | POST | /operator/generate-report | direct_route | api.operator.post.generate_report |
| http | GET | /operator/incidents | direct_route | api.operator.get.incidents |
| http | POST | /operator/incidents | direct_route | api.operator.post.incidents |
| http | GET | /operator/latest-run | direct_route | api.operator.get.latest_run |
| http | GET | /operator/live-summary | direct_route | api.operator.get.live_summary |
| http | POST | /operator/live-summary | direct_route | api.operator.post.live_summary |
| http | GET | /operator/objects | direct_route | api.operator.get.objects |
| http | POST | /operator/objects | direct_route | api.operator.post.objects |
| http | GET | /operator/profiles | direct_route | api.operator.get.profiles |
| http | GET | /operator/runner-status | direct_route | api.operator.get.runner_status |
| http | POST | /operator/save-config | direct_route | api.operator.post.save_config |
| http | POST | /operator/start-fusion | direct_route | api.operator.post.start_fusion |
| http | GET | /operator/traces | direct_route | api.operator.get.traces |
| http | POST | /operator/traces | direct_route | api.operator.post.traces |
| http | POST | /operator/validate-alignment | direct_route | api.operator.post.validate_alignment |
| http | POST | /operator/validate-alignment-full | direct_route | api.operator.post.validate_alignment_full |
| http | POST | /operator/write-zones | direct_route | api.operator.post.write_zones |
| http | GET | /status | direct_route | api.runner.status |
| http | GET | /{path*} | service_boundary | MP2-012.UI.SERVICE.DASHBOARD_STATIC_HTTP |
| http | HEAD | /{path*} | service_boundary | MP2-012.UI.SERVICE.DASHBOARD_STATIC_HTTP |
| http | OPTIONS | /{path*} | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | OPTIONS | /{path*} | service_boundary | MP2-012.UI.SERVICE.RUNTIME_HEALTH_METRICS_HTTP |
| http | OPTIONS | /{path*} | service_boundary | MP2-012.UI.SERVICE.LOCAL_RUNNER_HTTP |
| websocket | GET | /{path*} | service_boundary | MP2-012.UI.SERVICE.RUNTIME_FRAME_WEBSOCKET |

## Discovered Actions

| action_id | source | feature | command_or_endpoint |
| --- | --- | --- | --- |
| api.operator.get.camera_trust | operator_api | Operator GET /camera-trust | GET /operator/camera-trust |
| api.operator.get.cameras | operator_api | Operator GET /cameras | GET /operator/cameras |
| api.operator.get.configs | operator_api | Operator GET /configs | GET /operator/configs |
| api.operator.get.env | operator_api | Operator GET /env | GET /operator/env |
| api.operator.get.frames | operator_api | Operator GET /frames | GET /operator/frames |
| api.operator.get.incidents | operator_api | Operator GET /incidents | GET /operator/incidents |
| api.operator.get.latest_run | operator_api | Operator GET /latest-run | GET /operator/latest-run |
| api.operator.get.live_summary | operator_api | Operator GET /live-summary | GET /operator/live-summary |
| api.operator.get.objects | operator_api | Operator GET /objects | GET /operator/objects |
| api.operator.get.profiles | operator_api | Operator GET /profiles | GET /operator/profiles |
| api.operator.get.runner_status | operator_api | Operator GET /runner-status | GET /operator/runner-status |
| api.operator.get.traces | operator_api | Operator GET /traces | GET /operator/traces |
| api.operator.post.ask | operator_api | Operator POST /ask | POST /operator/ask |
| api.operator.post.calibrate | operator_api | Operator POST /calibrate | POST /operator/calibrate |
| api.operator.post.camera_trust | operator_api | Operator POST /camera-trust | POST /operator/camera-trust |
| api.operator.post.checksum | operator_api | Operator POST /checksum | POST /operator/checksum |
| api.operator.post.create_profile | operator_api | Operator POST /create-profile | POST /operator/create-profile |
| api.operator.post.frames | operator_api | Operator POST /frames | POST /operator/frames |
| api.operator.post.generate_report | operator_api | Operator POST /generate-report | POST /operator/generate-report |
| api.operator.post.incidents | operator_api | Operator POST /incidents | POST /operator/incidents |
| api.operator.post.live_summary | operator_api | Operator POST /live-summary | POST /operator/live-summary |
| api.operator.post.objects | operator_api | Operator POST /objects | POST /operator/objects |
| api.operator.post.save_config | operator_api | Operator POST /save-config | POST /operator/save-config |
| api.operator.post.start_fusion | operator_api | Operator POST /start-fusion | POST /operator/start-fusion |
| api.operator.post.traces | operator_api | Operator POST /traces | POST /operator/traces |
| api.operator.post.validate_alignment | operator_api | Operator POST /validate-alignment | POST /operator/validate-alignment |
| api.operator.post.validate_alignment_full | operator_api | Operator POST /validate-alignment-full | POST /operator/validate-alignment-full |
| api.operator.post.write_zones | operator_api | Operator POST /write-zones | POST /operator/write-zones |
| api.runner.cancel_job | runner_api | Cancel running job | POST /jobs/<id>/cancel |
| api.runner.commands | runner_api | Runner action registry | GET /commands |
| api.runner.execute | runner_api | Execute allowlisted command | POST /execute |
| api.runner.job_detail | runner_api | Runner job detail | GET /jobs/<id> |
| api.runner.jobs | runner_api | Recent runner jobs | GET /jobs |
| api.runner.status | runner_api | Runner status | GET /status |
| benchmark.edge_latency | benchmark | Edge Latency | python benchmarks/edge_latency.py |
| benchmark.event_throughput | benchmark | Event Throughput | python benchmarks/event_throughput.py |
| benchmark.gpu_batch_replay | benchmark | Gpu Batch Replay | python benchmarks/gpu_batch_replay.py |
| benchmark.gpu_fusion_scaling | benchmark | Gpu Fusion Scaling | python benchmarks/gpu_fusion_scaling.py |
| benchmark.run_backpressure | benchmark | Run Backpressure | python benchmarks/run_backpressure.py |
| benchmark.run_compute_backend_comparison | benchmark | Run Compute Backend Comparison | python benchmarks/run_compute_backend_comparison.py |
| benchmark.run_compute_equivalence | benchmark | Run Compute Equivalence | python benchmarks/run_compute_equivalence.py |
| benchmark.run_fusion_jitter | benchmark | Run Fusion Jitter | python benchmarks/run_fusion_jitter.py |
| benchmark.run_latency_breakdown | benchmark | Run Latency Breakdown | python benchmarks/run_latency_breakdown.py |
| benchmark.run_mapping_error | benchmark | Run Mapping Error | python benchmarks/run_mapping_error.py |
| benchmark.run_replay_determinism | benchmark | Run Replay Determinism | python benchmarks/run_replay_determinism.py |
| cli.ask | cli | metriplane ask | python -m metriplane.cli ask |
| cli.atlas | cli | metriplane atlas | python -m metriplane.cli atlas |
| cli.camera-trust | cli | metriplane camera-trust | python -m metriplane.cli camera-trust |
| cli.cleanup | cli | metriplane cleanup | python -m metriplane.cli cleanup |
| cli.command-center | cli | metriplane command-center | python -m metriplane.cli command-center |
| cli.contracts | cli | metriplane contracts | python -m metriplane.cli contracts |
| cli.counterfactual | cli | metriplane counterfactual | python -m metriplane.cli counterfactual |
| cli.demo | cli | metriplane demo | python -m metriplane.cli demo |
| cli.doctor | cli | metriplane doctor | python -m metriplane.cli doctor |
| cli.external | cli | metriplane external | python -m metriplane.cli external |
| cli.incidents | cli | metriplane incidents | python -m metriplane.cli incidents |
| cli.objects | cli | metriplane objects | python -m metriplane.cli objects |
| cli.query | cli | metriplane query | python -m metriplane.cli query |
| cli.replay | cli | metriplane replay | python -m metriplane.cli replay |
| cli.restart | cli | metriplane restart | python -m metriplane.cli restart |
| cli.rules | cli | metriplane rules | python -m metriplane.cli rules |
| cli.run | cli | metriplane run | python -m metriplane.cli run |
| cli.sentinel | cli | metriplane sentinel | python -m metriplane.cli sentinel |
| cli.start | cli | metriplane start | python -m metriplane.cli start |
| cli.status | cli | metriplane status | python -m metriplane.cli status |
| cli.stop | cli | metriplane stop | python -m metriplane.cli stop |
| cli.test | cli | metriplane test | python -m metriplane.cli test |
| cli.traces | cli | metriplane traces | python -m metriplane.cli traces |
| runner.atlas-demo | allowlist | Build Evidence Sample | _PYTHON -m metriplane.cli atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out web/dashboard/atlas_run --run-id metriplane_sample |
| runner.atlas-edge-doctor | allowlist | Run Edge Readiness | _PYTHON -m metriplane.cli atlas edge doctor --runs-root web/dashboard/atlas_run --min-free-mb 64 |
| runner.atlas-freeze-build | allowlist | Build Audit Snapshot | _PYTHON -m metriplane.cli atlas freeze build --root . --out web/dashboard/atlas_run/evidence_freeze |
| runner.atlas-lake-build | allowlist | Build Evidence Index | _PYTHON -m metriplane.cli atlas lake build --root web/dashboard/atlas_run --db web/dashboard/atlas_run/evidence_lake.sqlite |
| runner.atlas-pilot-kit | allowlist | Create Field Review Kit | _PYTHON -m metriplane.cli atlas pilot kit --out web/dashboard/atlas_run/pilot_kit |
| runner.atlas-protocol-export | allowlist | Export Protocol Files | _PYTHON -m metriplane.cli atlas protocol export --out web/dashboard/atlas_run/protocol |
| runner.atlas-query-demo-events | allowlist | Query Event Ledger | _PYTHON -m metriplane.cli atlas query events --run-dir web/dashboard/atlas_run --json |
| runner.atlas-regression-demo | allowlist | Replay Evidence Regression | _PYTHON -m metriplane.cli atlas test web/dashboard/atlas_run/regression_tests/INC-0001.yaml --json |
| runner.atlas-validate-pack | allowlist | Validate Evidence Rules | _PYTHON -m metriplane.cli atlas validate-pack configs/domain_packs/assembly_cell |
| runner.atlas-verify-demo | allowlist | Verify Incident Archive | _PYTHON -m metriplane.cli atlas bundle verify web/dashboard/atlas_run/evidence_bundles/INC-0001.zip |
| runner.backpressure | allowlist | Backpressure Test | ./tools/mp.sh backpressure |
| runner.cleanup | allowlist | Check Stale Processes | _PYTHON tools/ui_safe_cleanup.py |
| runner.deterministic-replay | allowlist | Deterministic Replay | ./tools/mp.sh deterministic-replay |
| runner.docker-check | allowlist | Check Docker | docker --version |
| runner.docker-demo-up | allowlist | Start Docker Demo | ./tools/docker_demo_up.sh |
| runner.docker-stop | allowlist | Stop Docker Demo | ./tools/docker_stop.sh |
| runner.doctor | allowlist | Doctor | _PYTHON -m metriplane.cli doctor |
| runner.gpu-benchmark | allowlist | GPU Benchmark | ./tools/mp.sh gpu-benchmark |
| runner.gpu-equivalence | allowlist | GPU Equivalence Test | ./tools/mp.sh gpu-equivalence |
| runner.gpu-smoke | allowlist | GPU Smoke Test | ./tools/mp.sh gpu-smoke |
| runner.health-degrade-cam1 | allowlist | Health Degradation | ./tools/mp.sh health-degrade-cam1 |
| runner.integration-isaac-export | allowlist | Export Isaac USD Replay | _PYTHON -m integrations.isaac.metriplane_to_usd --run-dir web/dashboard/atlas_run/evidence_bundles/INC-0001 --out web/dashboard/atlas_run/isaac/metriplane_replay.usda |
| runner.integration-omniverse-export | allowlist | Export Omniverse USD Replay | _PYTHON -m integrations.omniverse.metriplane_usd_replay --run-dir web/dashboard/atlas_run/evidence_bundles/INC-0001 --out web/dashboard/atlas_run/omniverse/metriplane_replay.usda |
| runner.integration-ros2-check | allowlist | Check ROS 2 Bridge Adapters | _PYTHON tools/check_ros2_adapters.py |
| runner.list-cameras | allowlist | List Cameras | _PYTHON tools/list_cameras.py |
| runner.preflight | allowlist | Preflight | ./tools/mp.sh preflight |
| runner.provenance | allowlist | Provenance Check | ./tools/mp.sh provenance |
| runner.run-demo-replay | allowlist | Run Demo Replay | _PYTHON tools/run_ui_demo_replay.py --runs-dir {metriplane_platform_runs_dir} |
| runner.run-fusion | allowlist | Run Fusion | ./tools/mp.sh run-fusion cpu 60 test |
| runner.sentinel-demo | allowlist | Build Command Center Sample | _PYTHON -m metriplane.cli sentinel run --config configs/sentinel_operator_demo.yaml --runs-dir {metriplane_platform_runs_dir} |
| runner.timing-breakdown | allowlist | Camera-Free Latency Check | _PYTHON tools/run_ui_timing_check.py |
| tool.analyze_id_stability_jsonl | tool | Analyze Id Stability Jsonl | python tools/analyze_id_stability_jsonl.py |
| tool.analyze_session_metrics | tool | Analyze Session Metrics | python tools/analyze_session_metrics.py |
| tool.audit_ui_functionality | tool | Audit Ui Functionality | python tools/audit_ui_functionality.py |
| tool.baseline_snapshot | tool | Baseline Snapshot | python tools/baseline_snapshot.py |
| tool.build_external_source_family_matrix | tool | Build External Source Family Matrix | python tools/build_external_source_family_matrix.py |
| tool.build_maniskill_pickcube_proof | tool | Build Maniskill Pickcube Proof | python tools/build_maniskill_pickcube_proof.py |
| tool.calibrate_intrinsics_chessboard | tool | Calibrate Intrinsics Chessboard | python tools/calibrate_intrinsics_chessboard.py |
| tool.calibrate_planar_homography | tool | Calibrate Planar Homography | python tools/calibrate_planar_homography.py |
| tool.capture_repository_protection | tool | Capture Repository Protection | python tools/capture_repository_protection.py |
| tool.check_blockers | tool | Check Blockers | python tools/check_blockers.py |
| tool.check_met77_transition | tool | Check Met77 Transition | python tools/check_met77_transition.py |
| tool.check_pr_contract | tool | Check Pr Contract | python tools/check_pr_contract.py |
| tool.check_repository_protection | tool | Check Repository Protection | python tools/check_repository_protection.py |
| tool.check_required_terminal | tool | Check Required Terminal | python tools/check_required_terminal.py |
| tool.check_ros2_adapters | tool | Check Ros2 Adapters | python tools/check_ros2_adapters.py |
| tool.command_center_up | tool | Command Center Up | tools/command_center_up.sh |
| tool.cross_adapter_gate | tool | Cross Adapter Gate | python tools/cross_adapter_gate.py |
| tool.cross_adapter_pytest | tool | Cross Adapter Pytest | python tools/cross_adapter_pytest.py |
| tool.dashboard_runner | tool | Dashboard Runner | tools/dashboard_runner.sh |
| tool.debug_alignment | tool | Debug Alignment | python tools/debug_alignment.py |
| tool.demo4_everything | tool | Demo4 Everything | tools/demo4_everything.sh |
| tool.discover_functional_surface | tool | Discover Functional Surface | python tools/discover_functional_surface.py |
| tool.docker_clean | tool | Docker Clean | tools/docker_clean.sh |
| tool.docker_demo_up | tool | Docker Demo Up | tools/docker_demo_up.sh |
| tool.docker_dummy_up | tool | Docker Dummy Up | tools/docker_dummy_up.sh |
| tool.docker_live_up | tool | Docker Live Up | tools/docker_live_up.sh |
| tool.docker_smoke_test | tool | Docker Smoke Test | tools/docker_smoke_test.sh |
| tool.docker_stop | tool | Docker Stop | tools/docker_stop.sh |
| tool.jetson_preflight | tool | Jetson Preflight | tools/jetson_preflight.sh |
| tool.list_cameras | tool | List Cameras | python tools/list_cameras.py |
| tool.main_health_broker | tool | Main Health Broker | python tools/main_health_broker.py |
| tool.mp | tool | Mp | tools/mp.sh |
| tool.observe_main_health | tool | Observe Main Health | python tools/observe_main_health.py |
| tool.plot_compute_backend_comparison | tool | Plot Compute Backend Comparison | python tools/plot_compute_backend_comparison.py |
| tool.preview_world_overlay | tool | Preview World Overlay | python tools/preview_world_overlay.py |
| tool.preview_world_overlay_multi | tool | Preview World Overlay Multi | python tools/preview_world_overlay_multi.py |
| tool.preview_world_overlay_multi_ws | tool | Preview World Overlay Multi Ws | python tools/preview_world_overlay_multi_ws.py |
| tool.preview_zones_overlay | tool | Preview Zones Overlay | python tools/preview_zones_overlay.py |
| tool.proof_m8_fusion | tool | Proof M8 Fusion | tools/proof_m8_fusion.sh |
| tool.release_artifacts | tool | Release Artifacts | python tools/release_artifacts.py |
| tool.report_alignment | tool | Report Alignment | python tools/report_alignment.py |
| tool.run_demo_all | tool | Run Demo All | tools/run_demo_all.sh |
| tool.run_fusion_preview | tool | Run Fusion Preview | python tools/run_fusion_preview.py |
| tool.run_fusion_yaml | tool | Run Fusion Yaml | python tools/run_fusion_yaml.py |
| tool.run_live_yaml | tool | Run Live Yaml | python tools/run_live_yaml.py |
| tool.run_ui_demo_replay | tool | Run Ui Demo Replay | python tools/run_ui_demo_replay.py |
| tool.run_ui_timing_check | tool | Run Ui Timing Check | python tools/run_ui_timing_check.py |
| tool.session_health_summary | tool | Session Health Summary | python tools/session_health_summary.py |
| tool.start_metriplane | tool | Start Metriplane | tools/start_metriplane.sh |
| tool.stop_the_line | tool | Stop The Line | python tools/stop_the_line.py |
| tool.ui_safe_cleanup | tool | Ui Safe Cleanup | python tools/ui_safe_cleanup.py |
| tool.validate-replay | tool | Validate Replay | tools/validate-replay.sh |
| tool.verify_m1_m6 | tool | Verify M1 M6 | tools/verify_m1_m6.sh |
| tool.verify_m6_offline | tool | Verify M6 Offline | tools/verify_m6_offline.sh |
| tool.ws_replay_jsonl | tool | Ws Replay Jsonl | python tools/ws_replay_jsonl.py |
| tool.ws_smoke_client | tool | Ws Smoke Client | python tools/ws_smoke_client.py |
| tool.ws_viewer_multi | tool | Ws Viewer Multi | python tools/ws_viewer_multi.py |
| tool.zones_report_jsonl | tool | Zones Report Jsonl | python tools/zones_report_jsonl.py |

## Dashboard Command Buttons

| file | label | command_id | disabled | needs_atlas |
| --- | --- | --- | --- | --- |
| web/dashboard/atlas.html | Build sample run | atlas-demo | False | False |
| web/dashboard/atlas.html | Run | atlas-demo | False | False |
| web/dashboard/atlas.html | Run | atlas-validate-pack | False | False |
| web/dashboard/atlas.html | Run | atlas-verify-demo | False | True |
| web/dashboard/atlas.html | Run | atlas-regression-demo | False | True |
| web/dashboard/atlas.html | Run | atlas-query-demo-events | False | True |
| web/dashboard/atlas.html | Run | atlas-lake-build | False | True |
| web/dashboard/atlas.html | Run | atlas-protocol-export | False | True |
| web/dashboard/atlas.html | Run | atlas-edge-doctor | False | True |
| web/dashboard/atlas.html | Run | atlas-pilot-kit | False | True |
| web/dashboard/atlas.html | Run | atlas-freeze-build | False | True |
| web/dashboard/atlas.html | Run | integration-omniverse-export | False | True |
| web/dashboard/atlas.html | Run | integration-ros2-check | False | False |
| web/dashboard/benchmarks.html | Run Deterministic Replay | deterministic-replay | False | False |
| web/dashboard/benchmarks.html | Run Backpressure | backpressure | False | False |
| web/dashboard/benchmarks.html | Run | deterministic-replay | False | False |
| web/dashboard/benchmarks.html | Run | backpressure | False | False |
| web/dashboard/benchmarks.html | Run | timing-breakdown | False | False |
| web/dashboard/benchmarks.html | Run | provenance | False | False |
| web/dashboard/benchmarks.html | Run | gpu-smoke | False | False |
| web/dashboard/benchmarks.html | Run | gpu-benchmark | False | False |
| web/dashboard/command_center_live.html | Build Command Center Sample | sentinel-demo | False | False |
| web/dashboard/help.html | Run Demo Replay | run-demo-replay | False | False |
| web/dashboard/help.html | Run | run-demo-replay | False | False |
| web/dashboard/index.html | Run Demo Replay | run-demo-replay | False | False |
| web/dashboard/index.html | Check System | doctor | False | False |
| web/dashboard/index.html | Run | run-demo-replay | False | False |
| web/dashboard/integrations.html | Check ROS 2 | integration-ros2-check | False | False |
| web/dashboard/integrations.html | Export USD Scene | integration-omniverse-export | False | True |
| web/dashboard/integrations.html | Check ROS 2 | integration-ros2-check | False | False |
| web/dashboard/integrations.html | Export Omniverse USD | integration-omniverse-export | False | True |
| web/dashboard/integrations.html | Export Isaac USD | integration-isaac-export | False | True |
| web/dashboard/integrations.html | Check Docker | docker-check | False | False |
| web/dashboard/integrations.html | Start demo | docker-demo-up | False | False |
| web/dashboard/integrations.html | Stop | docker-stop | False | False |
| web/dashboard/integrations.html | Check GPU | gpu-smoke | False | False |
| web/dashboard/integrations.html | Benchmark | gpu-benchmark | False | False |
| web/dashboard/integrations.html | Export protocol | atlas-protocol-export | False | True |
| web/dashboard/report.html | Run Demo Replay | run-demo-replay | False | False |
| web/dashboard/report.html | Verify | atlas-verify-demo | False | True |
| web/dashboard/report.html | Run check | atlas-regression-demo | False | True |
| web/dashboard/run.html | Run Demo Replay | run-demo-replay | False | False |
| web/dashboard/run.html | Run | run-demo-replay | False | False |
| web/dashboard/run.html | Run | deterministic-replay | False | False |
| web/dashboard/settings.html | Run Doctor | doctor | False | False |
| web/dashboard/settings.html | Check stale processes | cleanup | False | False |
| web/dashboard/settings.html | Run | doctor | False | False |
| web/dashboard/settings.html | Run | preflight | False | False |
| web/dashboard/settings.html | Run | list-cameras | False | False |
| web/dashboard/settings.html | Run | cleanup | False | False |

## Dashboard API Calls

| endpoint |
| --- |
| GET /commands |
| GET /jobs |
| GET /jobs/<id> |
| GET /operator/camera-trust |
| GET /operator/cameras |
| GET /operator/configs |
| GET /operator/env |
| GET /operator/frames |
| GET /operator/incidents |
| GET /operator/latest-run |
| GET /operator/live-summary |
| GET /operator/objects |
| GET /operator/profiles |
| GET /operator/runner-status |
| GET /operator/traces |
| GET /status |
| POST /execute |
| POST /jobs/<id>/cancel |
| POST /operator/ask |
| POST /operator/calibrate |
| POST /operator/checksum |
| POST /operator/create-profile |
| POST /operator/generate-report |
| POST /operator/save-config |
| POST /operator/start-fusion |
| POST /operator/validate-alignment |
| POST /operator/validate-alignment-full |
| POST /operator/write-zones |

## Dashboard Links

| file | label | href |
| --- | --- | --- |
| web/dashboard/atlas.html | Metri plane | index.html |
| web/dashboard/atlas.html | Start | index.html |
| web/dashboard/atlas.html | Setup | operator.html |
| web/dashboard/atlas.html | Run | run.html |
| web/dashboard/atlas.html | Live View | runtime.html |
| web/dashboard/atlas.html | Incident Report | report.html |
| web/dashboard/atlas.html | Command Center | command_center_live.html |
| web/dashboard/atlas.html | Evidence | atlas.html |
| web/dashboard/atlas.html | Integrations | integrations.html |
| web/dashboard/atlas.html | Benchmarks | benchmarks.html |
| web/dashboard/atlas.html | Settings | settings.html |
| web/dashboard/atlas.html | Help | help.html |
| web/dashboard/atlas.html | Open report guide | report.html |
| web/dashboard/atlas.html | Open generated file index | atlas_run/atlas_dashboard.html |
| web/dashboard/atlas.html | Open generated Incident Report | atlas_run/cell_truth_report.html |
| web/dashboard/atlas.html | Dashboard Open generated UI | atlas_run/atlas_dashboard.html |
| web/dashboard/atlas.html | Incident Report cell_truth_report.html | atlas_run/cell_truth_report.html |
| web/dashboard/atlas.html | Evidence bundle INC-0001.zip | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/atlas.html | Repeatable check INC-0001.yaml | atlas_run/regression_tests/INC-0001.yaml |
| web/dashboard/atlas.html | Privacy report privacy_report.json | atlas_run/privacy_report.json |
| web/dashboard/atlas.html | REST snapshot rest_snapshot.json | atlas_run/connectors/rest_snapshot.json |
| web/dashboard/atlas.html | USD replay metriplane_replay.usda | atlas_run/omniverse/metriplane_replay.usda |
| web/dashboard/atlas.html | Protocol Open protocol index | atlas_run/protocol/open_atlas_protocol_index.json |
| web/dashboard/atlas.html | 01 Set up cameras and zones Operator Setup creates calibrated world coordinates and runtime config. | operator.html |
| web/dashboard/atlas.html | 02 Watch live metric state Live State shows fused objects, telemetry, health, and evidence streams. | runtime.html |
| web/dashboard/atlas.html | 03 Investigate incidents Command Center makes incidents, forecasts, camera trust, and Q&A readable. | command_center_live.html |
| web/dashboard/atlas.html | 04 Review saved evidence Start with the Incident Report, then verify or reuse the supporting records and repeatable check. | atlas.html |
| web/dashboard/benchmarks.html | Metri plane | index.html |
| web/dashboard/benchmarks.html | Start | index.html |
| web/dashboard/benchmarks.html | Setup | operator.html |
| web/dashboard/benchmarks.html | Run | run.html |
| web/dashboard/benchmarks.html | Live View | runtime.html |
| web/dashboard/benchmarks.html | Incident Report | report.html |
| web/dashboard/benchmarks.html | Command Center | command_center_live.html |
| web/dashboard/benchmarks.html | Evidence | atlas.html |
| web/dashboard/benchmarks.html | Integrations | integrations.html |
| web/dashboard/benchmarks.html | Benchmarks | benchmarks.html |
| web/dashboard/benchmarks.html | Settings | settings.html |
| web/dashboard/benchmarks.html | Help | help.html |
| web/dashboard/benchmarks.html | Open | ../../docs/eval/evidence_matrix.md |
| web/dashboard/command_center.html | Open Live | command_center_live.html |
| web/dashboard/command_center.html | Open live Command Center | command_center_live.html |
| web/dashboard/command_center_live.html | Open snapshot | command_center.html |
| web/dashboard/help.html | Metri plane | index.html |
| web/dashboard/help.html | Start | index.html |
| web/dashboard/help.html | Setup | operator.html |
| web/dashboard/help.html | Run | run.html |
| web/dashboard/help.html | Live View | runtime.html |
| web/dashboard/help.html | Incident Report | report.html |
| web/dashboard/help.html | Command Center | command_center_live.html |
| web/dashboard/help.html | Evidence | atlas.html |
| web/dashboard/help.html | Integrations | integrations.html |
| web/dashboard/help.html | Benchmarks | benchmarks.html |
| web/dashboard/help.html | Settings | settings.html |
| web/dashboard/help.html | Help | help.html |
| web/dashboard/help.html | Open full runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/help.html | Settings | settings.html |
| web/dashboard/help.html | Run | run.html |
| web/dashboard/help.html | Integrations | integrations.html |
| web/dashboard/index.html | Metri plane | index.html |
| web/dashboard/index.html | Start | index.html |
| web/dashboard/index.html | Setup | operator.html |
| web/dashboard/index.html | Run | run.html |
| web/dashboard/index.html | Live View | runtime.html |
| web/dashboard/index.html | Incident Report | report.html |
| web/dashboard/index.html | Command Center | command_center_live.html |
| web/dashboard/index.html | Evidence | atlas.html |
| web/dashboard/index.html | Integrations | integrations.html |
| web/dashboard/index.html | Benchmarks | benchmarks.html |
| web/dashboard/index.html | Settings | settings.html |
| web/dashboard/index.html | Help | help.html |
| web/dashboard/index.html | Set Up Cameras | operator.html |
| web/dashboard/index.html | Open Latest Report | report.html |
| web/dashboard/index.html | Open Live View | runtime.html |
| web/dashboard/index.html | Open Report | report.html |
| web/dashboard/index.html | Open Evidence | atlas.html |
| web/dashboard/index.html | Run Start replay or live work Demo replay, live camera run, recorded session replay, and job history. Open Run | run.html |
| web/dashboard/index.html | Live View See movement and health World map, objects, zones, camera telemetry, and current status. Open Live View | runtime.html |
| web/dashboard/index.html | Incident Report Read what happened Plain-language findings first, with saved evidence and technical records still available. Open Report | report.html |
| web/dashboard/index.html | Command Center Investigate incidents Replay movement, inspect alerts, review camera trust, and ask grounded questions. Open Command Center | command_center_live.html |
| web/dashboard/index.html | Integrations Connect advanced tools Robot systems, simulation replay, Docker, GPU, and data exports. Open Integrations | integrations.html |
| web/dashboard/integrations.html | Metri plane | index.html |
| web/dashboard/integrations.html | Start | index.html |
| web/dashboard/integrations.html | Setup | operator.html |
| web/dashboard/integrations.html | Run | run.html |
| web/dashboard/integrations.html | Live View | runtime.html |
| web/dashboard/integrations.html | Incident Report | report.html |
| web/dashboard/integrations.html | Command Center | command_center_live.html |
| web/dashboard/integrations.html | Evidence | atlas.html |
| web/dashboard/integrations.html | Integrations | integrations.html |
| web/dashboard/integrations.html | Benchmarks | benchmarks.html |
| web/dashboard/integrations.html | Settings | settings.html |
| web/dashboard/integrations.html | Help | help.html |
| web/dashboard/integrations.html | Open instructions | ../../docs/ros2_bridge.md |
| web/dashboard/integrations.html | Open Omniverse file | atlas_run/omniverse/metriplane_replay.usda |
| web/dashboard/integrations.html | Open Isaac file | atlas_run/isaac/metriplane_replay.usda |
| web/dashboard/integrations.html | Instructions | ../../docs/isaac_omniverse_replay.md |
| web/dashboard/integrations.html | Open report | atlas_run/cell_truth_report.html |
| web/dashboard/integrations.html | Download proof | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/integrations.html | Evidence | atlas.html |
| web/dashboard/integrations.html | Report | ../../docs/gpu_compute_backend.md |
| web/dashboard/integrations.html | Open snapshot | atlas_run/connectors/rest_snapshot.json |
| web/dashboard/operator.html | ← Runtime Console | runtime.html |
| web/dashboard/operator.html | ← Back to Config | # |
| web/dashboard/operator.html | Full Runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/operator.html | Open full runbook → | ../../docs/operator_ui_runbook.md |
| web/dashboard/report.html | Metri plane | index.html |
| web/dashboard/report.html | Start | index.html |
| web/dashboard/report.html | Setup | operator.html |
| web/dashboard/report.html | Run | run.html |
| web/dashboard/report.html | Live View | runtime.html |
| web/dashboard/report.html | Incident Report | report.html |
| web/dashboard/report.html | Command Center | command_center_live.html |
| web/dashboard/report.html | Evidence | atlas.html |
| web/dashboard/report.html | Integrations | integrations.html |
| web/dashboard/report.html | Benchmarks | benchmarks.html |
| web/dashboard/report.html | Settings | settings.html |
| web/dashboard/report.html | Help | help.html |
| web/dashboard/report.html | Open Generated Incident Report | atlas_run/cell_truth_report.html |
| web/dashboard/report.html | Open Command Center | command_center_live.html |
| web/dashboard/report.html | Download Evidence Bundle | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/report.html | Open | atlas_run/cell_truth_report.html |
| web/dashboard/report.html | Evidence | atlas.html |
| web/dashboard/report.html | Download | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/report.html | View files | atlas.html |
| web/dashboard/report.html | Open check | atlas_run/regression_tests/INC-0001.yaml |
| web/dashboard/run.html | Metri plane | index.html |
| web/dashboard/run.html | Start | index.html |
| web/dashboard/run.html | Setup | operator.html |
| web/dashboard/run.html | Run | run.html |
| web/dashboard/run.html | Live View | runtime.html |
| web/dashboard/run.html | Incident Report | report.html |
| web/dashboard/run.html | Command Center | command_center_live.html |
| web/dashboard/run.html | Evidence | atlas.html |
| web/dashboard/run.html | Integrations | integrations.html |
| web/dashboard/run.html | Benchmarks | benchmarks.html |
| web/dashboard/run.html | Settings | settings.html |
| web/dashboard/run.html | Help | help.html |
| web/dashboard/run.html | Start Live Camera Setup | operator.html |
| web/dashboard/run.html | Open Live View | runtime.html |
| web/dashboard/run.html | Command Center | command_center_live.html |
| web/dashboard/run.html | Open Report | report.html |
| web/dashboard/run.html | Setup | operator.html |
| web/dashboard/run.html | Open | atlas.html |
| web/dashboard/run.html | Command helper Open script | ../../tools/run_ui_demo_replay.py |
| web/dashboard/run.html | Action registry Open allowlist | ../../metriplane/runner/allowlist.py |
| web/dashboard/run.html | Run data Open manifest | atlas_run/atlas_manifest.json |
| web/dashboard/run.html | Runbook Open guide | ../../docs/operator_ui_runbook.md |
| web/dashboard/runtime.html | Start | index.html |
| web/dashboard/runtime.html | Setup | operator.html |
| web/dashboard/runtime.html | Run | run.html |
| web/dashboard/runtime.html | Live View | runtime.html |
| web/dashboard/runtime.html | Incident Report | report.html |
| web/dashboard/runtime.html | Command Center | command_center_live.html |
| web/dashboard/runtime.html | Evidence | atlas.html |
| web/dashboard/runtime.html | Integrations | integrations.html |
| web/dashboard/runtime.html | Benchmarks | benchmarks.html |
| web/dashboard/runtime.html | Settings | settings.html |
| web/dashboard/runtime.html | Help | help.html |
| web/dashboard/runtime.html | Live State | #live-state |
| web/dashboard/runtime.html | Evidence | #evidence |
| web/dashboard/runtime.html | Runbook | #runbook |
| web/dashboard/runtime.html | Open Command Center | command_center_live.html |
| web/dashboard/runtime.html | View Runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/runtime.html | Full Runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/runtime.html | View Full Runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/runtime.html | Start from Operator Setup | operator.html |
| web/dashboard/runtime.html | Home | index.html |
| web/dashboard/runtime.html | Command Center | command_center_live.html |
| web/dashboard/runtime.html | Runbook | ../../docs/operator_ui_runbook.md |
| web/dashboard/settings.html | Metri plane | index.html |
| web/dashboard/settings.html | Start | index.html |
| web/dashboard/settings.html | Setup | operator.html |
| web/dashboard/settings.html | Run | run.html |
| web/dashboard/settings.html | Live View | runtime.html |
| web/dashboard/settings.html | Incident Report | report.html |
| web/dashboard/settings.html | Command Center | command_center_live.html |
| web/dashboard/settings.html | Evidence | atlas.html |
| web/dashboard/settings.html | Integrations | integrations.html |
| web/dashboard/settings.html | Benchmarks | benchmarks.html |
| web/dashboard/settings.html | Settings | settings.html |
| web/dashboard/settings.html | Help | help.html |
| web/dashboard/settings.html | Open | operator.html |
| web/dashboard/settings.html | Action registry Open allowlist | ../../metriplane/runner/allowlist.py |
| web/dashboard/settings.html | Runbook Open operator guide | ../../docs/operator_ui_runbook.md |
| web/dashboard/settings.html | Config Open example | ../../config.example.yaml |
| web/dashboard/settings.html | Calibration Open folder | ../../calib/ |

## Duplicate HTML IDs

No duplicate HTML IDs found.

## JavaScript Syntax Errors

No JavaScript syntax errors found by `node --check`.

## Duplicate Command IDs On The Same Card

No duplicate command IDs found on the same card.

## Atlas-Gated Buttons That Cannot Become Enabled

All `data-needs-atlas` buttons are wired to the Atlas artifact enable path.

## Endpoint Method Separation

GET and POST calls are inventoried independently; one method never certifies the other.
