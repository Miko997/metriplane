<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Functionality Inventory

Generated: `2026-06-14T17:56:01+00:00`

## Discovered Actions

| action_id | source | feature | command_or_endpoint |
| --- | --- | --- | --- |
| runner.run-demo-replay | allowlist | Run Demo Replay | _PYTHON tools/run_ui_demo_replay.py |
| runner.doctor | allowlist | Doctor | _PYTHON -m metriplane.cli doctor |
| runner.preflight | allowlist | Preflight | ./tools/mp.sh preflight |
| runner.deterministic-replay | allowlist | Deterministic Replay | ./tools/mp.sh deterministic-replay |
| runner.backpressure | allowlist | Backpressure Test | ./tools/mp.sh backpressure |
| runner.gpu-smoke | allowlist | GPU Smoke Test | ./tools/mp.sh gpu-smoke |
| runner.gpu-benchmark | allowlist | GPU Benchmark | ./tools/mp.sh gpu-benchmark |
| runner.health-degrade-cam1 | allowlist | Health Degradation | ./tools/mp.sh health-degrade-cam1 |
| runner.gpu-equivalence | allowlist | GPU Equivalence Test | ./tools/mp.sh gpu-equivalence |
| runner.run-fusion | allowlist | Run Fusion | ./tools/mp.sh run-fusion cpu 60 test |
| runner.provenance | allowlist | Provenance Check | ./tools/mp.sh provenance |
| runner.timing-breakdown | allowlist | Camera-Free Latency Check | _PYTHON tools/run_ui_timing_check.py |
| runner.list-cameras | allowlist | List Cameras | _PYTHON tools/list_cameras.py |
| runner.sentinel-demo | allowlist | Build Command Center Sample | _PYTHON -m metriplane.cli sentinel run --config configs/sentinel_operator_demo.yaml --run-id metriplane_demo --runs-dir _RUNS_DIR |
| runner.atlas-validate-pack | allowlist | Validate Evidence Rules | _PYTHON -m metriplane.cli atlas validate-pack configs/domain_packs/assembly_cell |
| runner.atlas-demo | allowlist | Build Evidence Sample | _PYTHON -m metriplane.cli atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out _ATLAS_UI_RUN --run-id metriplane_sample |
| runner.atlas-verify-demo | allowlist | Verify Incident Archive | _PYTHON -m metriplane.cli atlas bundle verify _ATLAS_UI_BUNDLE |
| runner.atlas-regression-demo | allowlist | Replay Evidence Regression | _PYTHON -m metriplane.cli atlas test _ATLAS_UI_REGRESSION --json |
| runner.atlas-query-demo-events | allowlist | Query Event Ledger | _PYTHON -m metriplane.cli atlas query events --run-dir _ATLAS_UI_RUN --json |
| runner.atlas-lake-build | allowlist | Build Evidence Index | _PYTHON -m metriplane.cli atlas lake build --root _ATLAS_UI_RUN --db f'{_ATLAS_UI_RUN}/evidence_lake.sqlite' |
| runner.atlas-protocol-export | allowlist | Export Protocol Files | _PYTHON -m metriplane.cli atlas protocol export --out f'{_ATLAS_UI_RUN}/protocol' |
| runner.atlas-pilot-kit | allowlist | Create Field Review Kit | _PYTHON -m metriplane.cli atlas pilot kit --out f'{_ATLAS_UI_RUN}/pilot_kit' |
| runner.atlas-freeze-build | allowlist | Build Audit Snapshot | _PYTHON -m metriplane.cli atlas freeze build --root . --out f'{_ATLAS_UI_RUN}/evidence_freeze' |
| runner.atlas-edge-doctor | allowlist | Run Edge Readiness | _PYTHON -m metriplane.cli atlas edge doctor --runs-root _ATLAS_UI_RUN --min-free-mb 64 |
| runner.integration-omniverse-export | allowlist | Export Omniverse USD Replay | _PYTHON -m integrations.omniverse.metriplane_usd_replay --run-dir _ATLAS_UI_BUNDLE_DIR --out f'{_ATLAS_UI_RUN}/omniverse/metriplane_replay.usda' |
| runner.integration-isaac-export | allowlist | Export Isaac USD Replay | _PYTHON -m integrations.isaac.metriplane_to_usd --run-dir _ATLAS_UI_BUNDLE_DIR --out f'{_ATLAS_UI_RUN}/isaac/metriplane_replay.usda' |
| runner.integration-ros2-check | allowlist | Check ROS 2 Bridge Adapters | _PYTHON tools/check_ros2_adapters.py |
| runner.docker-check | allowlist | Check Docker | docker --version |
| runner.docker-demo-up | allowlist | Start Docker Demo | ./tools/docker_demo_up.sh |
| runner.docker-stop | allowlist | Stop Docker Demo | ./tools/docker_stop.sh |
| runner.cleanup | allowlist | Check Stale Processes | _PYTHON tools/ui_safe_cleanup.py |
| cli.ask | cli | metriplane ask | python -m metriplane.cli ask |
| cli.atlas | cli | metriplane atlas | python -m metriplane.cli atlas |
| cli.camera-trust | cli | metriplane camera-trust | python -m metriplane.cli camera-trust |
| cli.cleanup | cli | metriplane cleanup | python -m metriplane.cli cleanup |
| cli.command-center | cli | metriplane command-center | python -m metriplane.cli command-center |
| cli.contracts | cli | metriplane contracts | python -m metriplane.cli contracts |
| cli.counterfactual | cli | metriplane counterfactual | python -m metriplane.cli counterfactual |
| cli.doctor | cli | metriplane doctor | python -m metriplane.cli doctor |
| cli.incidents | cli | metriplane incidents | python -m metriplane.cli incidents |
| cli.objects | cli | metriplane objects | python -m metriplane.cli objects |
| cli.query | cli | metriplane query | python -m metriplane.cli query |
| cli.replay | cli | metriplane replay | python -m metriplane.cli replay |
| cli.restart | cli | metriplane restart | python -m metriplane.cli restart |
| cli.rules | cli | metriplane rules | python -m metriplane.cli rules |
| cli.sentinel | cli | metriplane sentinel | python -m metriplane.cli sentinel |
| cli.start | cli | metriplane start | python -m metriplane.cli start |
| cli.status | cli | metriplane status | python -m metriplane.cli status |
| cli.stop | cli | metriplane stop | python -m metriplane.cli stop |
| cli.test | cli | metriplane test | python -m metriplane.cli test |
| cli.traces | cli | metriplane traces | python -m metriplane.cli traces |
| api.operator.get.env | operator_api | Operator GET /env | GET /operator/env |
| api.operator.get.cameras | operator_api | Operator GET /cameras | GET /operator/cameras |
| api.operator.get.profiles | operator_api | Operator GET /profiles | GET /operator/profiles |
| api.operator.get.configs | operator_api | Operator GET /configs | GET /operator/configs |
| api.operator.get.latest_run | operator_api | Operator GET /latest-run | GET /operator/latest-run |
| api.operator.get.runner_status | operator_api | Operator GET /runner-status | GET /operator/runner-status |
| api.operator.get.live_summary | operator_api | Operator GET /live-summary | GET /operator/live-summary |
| api.operator.get.objects | operator_api | Operator GET /objects | GET /operator/objects |
| api.operator.get.incidents | operator_api | Operator GET /incidents | GET /operator/incidents |
| api.operator.get.traces | operator_api | Operator GET /traces | GET /operator/traces |
| api.operator.get.camera_trust | operator_api | Operator GET /camera-trust | GET /operator/camera-trust |
| api.operator.get.frames | operator_api | Operator GET /frames | GET /operator/frames |
| api.operator.post.create_profile | operator_api | Operator POST /create-profile | POST /operator/create-profile |
| api.operator.post.write_zones | operator_api | Operator POST /write-zones | POST /operator/write-zones |
| api.operator.post.save_config | operator_api | Operator POST /save-config | POST /operator/save-config |
| api.operator.post.start_fusion | operator_api | Operator POST /start-fusion | POST /operator/start-fusion |
| api.operator.post.calibrate | operator_api | Operator POST /calibrate | POST /operator/calibrate |
| api.operator.post.validate_alignment | operator_api | Operator POST /validate-alignment | POST /operator/validate-alignment |
| api.operator.post.validate_alignment_full | operator_api | Operator POST /validate-alignment-full | POST /operator/validate-alignment-full |
| api.operator.post.generate_report | operator_api | Operator POST /generate-report | POST /operator/generate-report |
| api.operator.post.checksum | operator_api | Operator POST /checksum | POST /operator/checksum |
| api.operator.post.live_summary | operator_api | Operator POST /live-summary | POST /operator/live-summary |
| api.operator.post.objects | operator_api | Operator POST /objects | POST /operator/objects |
| api.operator.post.incidents | operator_api | Operator POST /incidents | POST /operator/incidents |
| api.operator.post.traces | operator_api | Operator POST /traces | POST /operator/traces |
| api.operator.post.camera_trust | operator_api | Operator POST /camera-trust | POST /operator/camera-trust |
| api.operator.post.frames | operator_api | Operator POST /frames | POST /operator/frames |
| api.operator.post.ask | operator_api | Operator POST /ask | POST /operator/ask |
| api.runner.status | runner_api | Runner status | GET /status |
| api.runner.commands | runner_api | Runner action registry | GET /commands |
| api.runner.jobs | runner_api | Recent runner jobs | GET /jobs |
| api.runner.job_detail | runner_api | Runner job detail | GET /jobs/<id> |
| api.runner.execute | runner_api | Execute allowlisted command | POST /execute |
| api.runner.cancel_job | runner_api | Cancel running job | POST /jobs/<id>/cancel |
| tool.analyze_id_stability_jsonl | tool | Analyze Id Stability Jsonl | python tools/analyze_id_stability_jsonl.py |
| tool.analyze_session_metrics | tool | Analyze Session Metrics | python tools/analyze_session_metrics.py |
| tool.audit_ui_functionality | tool | Audit Ui Functionality | python tools/audit_ui_functionality.py |
| tool.calibrate_intrinsics_chessboard | tool | Calibrate Intrinsics Chessboard | python tools/calibrate_intrinsics_chessboard.py |
| tool.calibrate_planar_homography | tool | Calibrate Planar Homography | python tools/calibrate_planar_homography.py |
| tool.check_ros2_adapters | tool | Check Ros2 Adapters | python tools/check_ros2_adapters.py |
| tool.debug_alignment | tool | Debug Alignment | python tools/debug_alignment.py |
| tool.list_cameras | tool | List Cameras | python tools/list_cameras.py |
| tool.plot_compute_backend_comparison | tool | Plot Compute Backend Comparison | python tools/plot_compute_backend_comparison.py |
| tool.preview_world_overlay | tool | Preview World Overlay | python tools/preview_world_overlay.py |
| tool.preview_world_overlay_multi | tool | Preview World Overlay Multi | python tools/preview_world_overlay_multi.py |
| tool.preview_world_overlay_multi_ws | tool | Preview World Overlay Multi Ws | python tools/preview_world_overlay_multi_ws.py |
| tool.preview_zones_overlay | tool | Preview Zones Overlay | python tools/preview_zones_overlay.py |
| tool.report_alignment | tool | Report Alignment | python tools/report_alignment.py |
| tool.run_fusion_preview | tool | Run Fusion Preview | python tools/run_fusion_preview.py |
| tool.run_fusion_yaml | tool | Run Fusion Yaml | python tools/run_fusion_yaml.py |
| tool.run_live_yaml | tool | Run Live Yaml | python tools/run_live_yaml.py |
| tool.run_ui_demo_replay | tool | Run Ui Demo Replay | python tools/run_ui_demo_replay.py |
| tool.run_ui_timing_check | tool | Run Ui Timing Check | python tools/run_ui_timing_check.py |
| tool.session_health_summary | tool | Session Health Summary | python tools/session_health_summary.py |
| tool.ui_safe_cleanup | tool | Ui Safe Cleanup | python tools/ui_safe_cleanup.py |
| tool.ws_replay_jsonl | tool | Ws Replay Jsonl | python tools/ws_replay_jsonl.py |
| tool.ws_smoke_client | tool | Ws Smoke Client | python tools/ws_smoke_client.py |
| tool.ws_viewer_multi | tool | Ws Viewer Multi | python tools/ws_viewer_multi.py |
| tool.zones_report_jsonl | tool | Zones Report Jsonl | python tools/zones_report_jsonl.py |
| tool.command_center_up | tool | Command Center Up | tools/command_center_up.sh |
| tool.dashboard_runner | tool | Dashboard Runner | tools/dashboard_runner.sh |
| tool.demo4_everything | tool | Demo4 Everything | tools/demo4_everything.sh |
| tool.docker_clean | tool | Docker Clean | tools/docker_clean.sh |
| tool.docker_demo_up | tool | Docker Demo Up | tools/docker_demo_up.sh |
| tool.docker_dummy_up | tool | Docker Dummy Up | tools/docker_dummy_up.sh |
| tool.docker_live_up | tool | Docker Live Up | tools/docker_live_up.sh |
| tool.docker_smoke_test | tool | Docker Smoke Test | tools/docker_smoke_test.sh |
| tool.docker_stop | tool | Docker Stop | tools/docker_stop.sh |
| tool.jetson_preflight | tool | Jetson Preflight | tools/jetson_preflight.sh |
| tool.mp | tool | Mp | tools/mp.sh |
| tool.proof_m8_fusion | tool | Proof M8 Fusion | tools/proof_m8_fusion.sh |
| tool.run_demo_all | tool | Run Demo All | tools/run_demo_all.sh |
| tool.start_metriplane | tool | Start Metriplane | tools/start_metriplane.sh |
| tool.validate-replay | tool | Validate Replay | tools/validate-replay.sh |
| tool.verify_m1_m6 | tool | Verify M1 M6 | tools/verify_m1_m6.sh |
| tool.verify_m6_offline | tool | Verify M6 Offline | tools/verify_m6_offline.sh |
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
| GET /jobs/ |
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
| POST /jobs/ |
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
| web/dashboard/atlas.html | Metri Plane | index.html |
| web/dashboard/atlas.html | Start | index.html |
| web/dashboard/atlas.html | Setup | operator.html |
| web/dashboard/atlas.html | Run | run.html |
| web/dashboard/atlas.html | Live View | runtime.html |
| web/dashboard/atlas.html | Cell Report | report.html |
| web/dashboard/atlas.html | Command Center | command_center_live.html |
| web/dashboard/atlas.html | Evidence | atlas.html |
| web/dashboard/atlas.html | Integrations | integrations.html |
| web/dashboard/atlas.html | Benchmarks | benchmarks.html |
| web/dashboard/atlas.html | Settings | settings.html |
| web/dashboard/atlas.html | Help | help.html |
| web/dashboard/atlas.html | Open cell report | report.html |
| web/dashboard/atlas.html | Open evidence dashboard | atlas_run/atlas_dashboard.html |
| web/dashboard/atlas.html | Open truth report | atlas_run/cell_truth_report.html |
| web/dashboard/atlas.html | Dashboard Open generated UI | atlas_run/atlas_dashboard.html |
| web/dashboard/atlas.html | Truth report cell_truth_report.html | atlas_run/cell_truth_report.html |
| web/dashboard/atlas.html | Incident archive INC-0001.zip | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/atlas.html | Regression INC-0001.yaml | atlas_run/regression_tests/INC-0001.yaml |
| web/dashboard/atlas.html | Privacy report privacy_report.json | atlas_run/privacy_report.json |
| web/dashboard/atlas.html | REST snapshot rest_snapshot.json | atlas_run/connectors/rest_snapshot.json |
| web/dashboard/atlas.html | USD replay metriplane_replay.usda | atlas_run/omniverse/metriplane_replay.usda |
| web/dashboard/atlas.html | Protocol Open protocol index | atlas_run/protocol/open_atlas_protocol_index.json |
| web/dashboard/atlas.html | 01 Set up cameras and zones Operator Setup creates calibrated world coordinates and runtime config. | operator.html |
| web/dashboard/atlas.html | 02 Watch live metric state Live State shows fused objects, telemetry, health, and evidence streams. | runtime.html |
| web/dashboard/atlas.html | 03 Investigate incidents Command Center makes incidents, forecasts, camera trust, and Q&A readable. | command_center_live.html |
| web/dashboard/atlas.html | 04 Review evidence Evidence Review turns a run into reusable records, tests, exports, and review artifacts. | atlas.html |
| web/dashboard/benchmarks.html | Metri Plane | index.html |
| web/dashboard/benchmarks.html | Start | index.html |
| web/dashboard/benchmarks.html | Setup | operator.html |
| web/dashboard/benchmarks.html | Run | run.html |
| web/dashboard/benchmarks.html | Live View | runtime.html |
| web/dashboard/benchmarks.html | Cell Report | report.html |
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
| web/dashboard/help.html | Metri Plane | index.html |
| web/dashboard/help.html | Start | index.html |
| web/dashboard/help.html | Setup | operator.html |
| web/dashboard/help.html | Run | run.html |
| web/dashboard/help.html | Live View | runtime.html |
| web/dashboard/help.html | Cell Report | report.html |
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
| web/dashboard/index.html | Metri Plane | index.html |
| web/dashboard/index.html | Start | index.html |
| web/dashboard/index.html | Setup | operator.html |
| web/dashboard/index.html | Run | run.html |
| web/dashboard/index.html | Live View | runtime.html |
| web/dashboard/index.html | Cell Report | report.html |
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
| web/dashboard/index.html | Cell Report Read what happened Summary, findings, movement history, proof, and recommended next actions. Open Report | report.html |
| web/dashboard/index.html | Command Center Investigate incidents Replay movement, inspect alerts, review camera trust, and ask grounded questions. Open Command Center | command_center_live.html |
| web/dashboard/index.html | Integrations Connect advanced tools Robot systems, simulation replay, Docker, GPU, and data exports. Open Integrations | integrations.html |
| web/dashboard/integrations.html | Metri Plane | index.html |
| web/dashboard/integrations.html | Start | index.html |
| web/dashboard/integrations.html | Setup | operator.html |
| web/dashboard/integrations.html | Run | run.html |
| web/dashboard/integrations.html | Live View | runtime.html |
| web/dashboard/integrations.html | Cell Report | report.html |
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
| web/dashboard/report.html | Metri Plane | index.html |
| web/dashboard/report.html | Start | index.html |
| web/dashboard/report.html | Setup | operator.html |
| web/dashboard/report.html | Run | run.html |
| web/dashboard/report.html | Live View | runtime.html |
| web/dashboard/report.html | Cell Report | report.html |
| web/dashboard/report.html | Command Center | command_center_live.html |
| web/dashboard/report.html | Evidence | atlas.html |
| web/dashboard/report.html | Integrations | integrations.html |
| web/dashboard/report.html | Benchmarks | benchmarks.html |
| web/dashboard/report.html | Settings | settings.html |
| web/dashboard/report.html | Help | help.html |
| web/dashboard/report.html | Open Full Report | atlas_run/cell_truth_report.html |
| web/dashboard/report.html | Open Command Center | command_center_live.html |
| web/dashboard/report.html | Export Proof | atlas_run/evidence_bundles/INC-0001.zip |
| web/dashboard/report.html | Open | atlas_run/cell_truth_report.html |
| web/dashboard/report.html | Evidence | atlas.html |
| web/dashboard/run.html | Metri Plane | index.html |
| web/dashboard/run.html | Start | index.html |
| web/dashboard/run.html | Setup | operator.html |
| web/dashboard/run.html | Run | run.html |
| web/dashboard/run.html | Live View | runtime.html |
| web/dashboard/run.html | Cell Report | report.html |
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
| web/dashboard/runtime.html | Cell Report | report.html |
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
| web/dashboard/settings.html | Metri Plane | index.html |
| web/dashboard/settings.html | Start | index.html |
| web/dashboard/settings.html | Setup | operator.html |
| web/dashboard/settings.html | Run | run.html |
| web/dashboard/settings.html | Live View | runtime.html |
| web/dashboard/settings.html | Cell Report | report.html |
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

## Read-Only Endpoint Fallback Coverage

| action_id | endpoint | notes |
| --- | --- | --- |
| api.operator.post.live_summary | POST /operator/live-summary | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.objects | POST /operator/objects | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.incidents | POST /operator/incidents | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.traces | POST /operator/traces | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.camera_trust | POST /operator/camera-trust | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.frames | POST /operator/frames | Covered by read-only GET fallback for an observe-only endpoint. |
