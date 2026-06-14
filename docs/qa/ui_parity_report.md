<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Parity Report

Generated: `2026-06-14T18:38:28+00:00`

Static UI/API release gate: **PASS**
Browser E2E release gate: **PASS**
Integration runtime gate: **ROS 2 manual runtime smoke PASS; Omniverse manual evidence PARTIAL; Isaac Sim and Docker runtimes NOT RUN**

## Manual Integration Runtime Smoke

| Runtime | Result | Evidence | Boundary |
| --- | --- | --- | --- |
| ROS 2 | PASS | `evidence/experiments/ros2_runtime_manual_2026-06-14.md` | Manual one-environment smoke; bridge package builds, `ros2 run` resolves, launch publishes `/metriplane/frame_state`, and bag capture recorded messages. No latency, reliability, robot-control, safety, or production-runtime claim. |
| Omniverse | PARTIAL | `evidence/experiments/omniverse_runtime_manual_2026-06-14.md` | Generated USDA replay artifact is checksummed; no raw Omniverse open log or screenshot captured. No simulator runtime, latency, physics-correctness, or production-runtime claim. |
| Isaac Sim | NOT RUN | - | No manual runtime-open evidence captured. |
| Docker runtime | NOT RUN | - | No manual container runtime evidence captured in this pass. |

## Clean Checkout Fixture Gate

`tests/test_release_fixture_integrity.py` guards deterministic fixture files required by the release tests so CI fails early if small checked-in fixtures are missing from a clean checkout. Raw local runs, generated outputs, and large media remain ignored.

## Summary

| metric | value |
| --- | --- |
| total_discovered_features | 138 |
| ui_full | 63 |
| ui_partial | 16 |
| ui_copy_command_only | 12 |
| ui_disabled_with_reason | 0 |
| ui_missing | 0 |
| cli_only_documented | 47 |
| planned_only | 0 |
| broken_buttons | 0 |
| unsupported_claims_found | 0 |
| duplicate_html_ids | 0 |
| js_syntax_errors | 0 |
| js_syntax_check_unavailable | 0 |
| buttons_with_duplicate_command_id_on_same_card | 0 |
| data_needs_atlas_buttons_never_enabled | 0 |
| read_only_fallback_endpoints | 6 |
| critical_bugs | 0 |
| high_bugs | 0 |

## Stable Features Fully Available In UI

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runner.run-demo-replay | Run Demo Replay | metriplane/runner/allowlist.py | _PYTHON tools/run_ui_demo_replay.py | web/dashboard/help.html; web/dashboard/help.html; web/dashboard/index.html; web/dashboard/index.html; web/dashboard/report.html; web/dashboard/run.html; web/dashboard/run.html | Run Demo Replay; Run; Run Demo Replay; Run; Run Demo Replay; Run Demo Replay; Run | ui_full | P0 | Build the camera-free demo replay, Command Center sample, evidence workspace, and USD export |
| runner.doctor | Doctor | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli doctor | web/dashboard/index.html; web/dashboard/settings.html; web/dashboard/settings.html | Check System; Run Doctor; Run | ui_full | P0 | Run health diagnostics across 8 system checks |
| runner.preflight | Preflight | metriplane/runner/allowlist.py | ./tools/mp.sh preflight | web/dashboard/settings.html | Run | ui_full | P0 | Check system dependencies and configuration |
| runner.deterministic-replay | Deterministic Replay | metriplane/runner/allowlist.py | ./tools/mp.sh deterministic-replay | web/dashboard/benchmarks.html; web/dashboard/benchmarks.html; web/dashboard/run.html | Run Deterministic Replay; Run; Run | ui_full | P1 | M9.1: Verify bit-exact reproducibility across runs |
| runner.backpressure | Backpressure Test | metriplane/runner/allowlist.py | ./tools/mp.sh backpressure | web/dashboard/benchmarks.html; web/dashboard/benchmarks.html | Run Backpressure; Run | ui_full | P1 | M9.2: Test graceful degradation under synthetic load |
| runner.gpu-smoke | GPU Smoke Test | metriplane/runner/allowlist.py | ./tools/mp.sh gpu-smoke | web/dashboard/benchmarks.html; web/dashboard/integrations.html | Run; Check GPU | ui_full | P1 | M9.6: Verify CuPy and CUDA device availability |
| runner.gpu-benchmark | GPU Benchmark | metriplane/runner/allowlist.py | ./tools/mp.sh gpu-benchmark | web/dashboard/benchmarks.html; web/dashboard/integrations.html | Run; Benchmark | ui_full | P1 | M9.6: Compare CPU vs GPU compute backend performance |
| runner.provenance | Provenance Check | metriplane/runner/allowlist.py | ./tools/mp.sh provenance | web/dashboard/benchmarks.html | Run | ui_full | P2 | M9.4: Verify run_id, config_hash, and git commit stamping without opening cameras |
| runner.timing-breakdown | Camera-Free Latency Check | metriplane/runner/allowlist.py | _PYTHON tools/run_ui_timing_check.py | web/dashboard/benchmarks.html | Run | ui_full | P1 | Measure replay/rule-engine latency without opening local cameras |
| runner.list-cameras | List Cameras | metriplane/runner/allowlist.py | _PYTHON tools/list_cameras.py | web/dashboard/settings.html | Run | ui_full | P0 | Discover available v4l2 camera devices (JSON output) |
| runner.sentinel-demo | Build Command Center Sample | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli sentinel run --config configs/sentinel_operator_demo.yaml --run-id metriplane_demo --runs-dir _RUNS_DIR | web/dashboard/command_center_live.html | Build Command Center Sample | ui_full | P0 | Run the camera-free incident sample and write a run the Command Center can display |
| runner.atlas-validate-pack | Validate Evidence Rules | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas validate-pack configs/domain_packs/assembly_cell | web/dashboard/atlas.html | Run | ui_full | P2 | Validate the checked-in assembly-cell evidence rules |
| runner.atlas-demo | Build Evidence Sample | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas run --session-jsonl datasets/demo/atlas/assembly_cell_missing_tool.jsonl --pack configs/domain_packs/assembly_cell --out _ATLAS_UI_RUN --run-id metriplane_sample | web/dashboard/atlas.html; web/dashboard/atlas.html | Build sample run; Run | ui_full | P1 | Run the MetriPlane evidence workflow over the assembly-cell sample and publish local dashboard artifacts |
| runner.atlas-verify-demo | Verify Incident Archive | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas bundle verify _ATLAS_UI_BUNDLE | web/dashboard/atlas.html; web/dashboard/report.html | Run; Verify | ui_full | P1 | Verify checksums and required contents for the generated incident evidence archive |
| runner.atlas-regression-demo | Replay Evidence Regression | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas test _ATLAS_UI_REGRESSION --json | web/dashboard/atlas.html | Run | ui_full | P2 | Replay the generated physical regression spec for the incident |
| runner.atlas-query-demo-events | Query Event Ledger | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas query events --run-dir _ATLAS_UI_RUN --json | web/dashboard/atlas.html | Run | ui_full | P2 | Return the run's physical event ledger as JSON |
| runner.atlas-lake-build | Build Evidence Index | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas lake build --root _ATLAS_UI_RUN --db f'{_ATLAS_UI_RUN}/evidence_lake.sqlite' | web/dashboard/atlas.html | Run | ui_full | P2 | Index generated manifests, incidents, and events into a local SQLite evidence index |
| runner.atlas-protocol-export | Export Protocol Files | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas protocol export --out f'{_ATLAS_UI_RUN}/protocol' | web/dashboard/atlas.html; web/dashboard/integrations.html | Run; Export protocol | ui_full | P2 | Write local protocol schema/index artifacts for external interchange |
| runner.atlas-pilot-kit | Create Field Review Kit | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas pilot kit --out f'{_ATLAS_UI_RUN}/pilot_kit' | web/dashboard/atlas.html | Run | ui_full | P2 | Create external review checklist, script, and review templates |
| runner.atlas-freeze-build | Build Audit Snapshot | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas freeze build --root . --out f'{_ATLAS_UI_RUN}/evidence_freeze' | web/dashboard/atlas.html | Run | ui_full | P2 | Build a local evidence audit and review-note snapshot |
| runner.atlas-edge-doctor | Run Edge Readiness | metriplane/runner/allowlist.py | _PYTHON -m metriplane.cli atlas edge doctor --runs-root _ATLAS_UI_RUN --min-free-mb 64 | web/dashboard/atlas.html | Run | ui_full | P2 | Check generated evidence storage and edge-appliance readiness signals |
| runner.integration-omniverse-export | Export Omniverse USD Replay | metriplane/runner/allowlist.py | _PYTHON -m integrations.omniverse.metriplane_usd_replay --run-dir _ATLAS_UI_BUNDLE_DIR --out f'{_ATLAS_UI_RUN}/omniverse/metriplane_replay.usda' | web/dashboard/atlas.html; web/dashboard/integrations.html; web/dashboard/integrations.html | Run; Export USD Scene; Export Omniverse USD | ui_full | P1 | Write a USD replay scene from the current MetriPlane evidence run |
| runner.integration-isaac-export | Export Isaac USD Replay | metriplane/runner/allowlist.py | _PYTHON -m integrations.isaac.metriplane_to_usd --run-dir _ATLAS_UI_BUNDLE_DIR --out f'{_ATLAS_UI_RUN}/isaac/metriplane_replay.usda' | web/dashboard/integrations.html | Export Isaac USD | ui_full | P1 | Write a USD replay scene compatible with Isaac Sim |
| runner.integration-ros2-check | Check ROS 2 Bridge Adapters | metriplane/runner/allowlist.py | _PYTHON tools/check_ros2_adapters.py | web/dashboard/atlas.html; web/dashboard/integrations.html; web/dashboard/integrations.html | Run; Check ROS 2; Check ROS 2 | ui_full | P1 | Run ROS-free checks for the MetriPlane ROS 2 message adapters |
| runner.docker-check | Check Docker | metriplane/runner/allowlist.py | docker --version | web/dashboard/integrations.html | Check Docker | ui_full | P1 | Check whether Docker is available for the local demo container path |
| runner.docker-demo-up | Start Docker Demo | metriplane/runner/allowlist.py | ./tools/docker_demo_up.sh | web/dashboard/integrations.html | Start demo | ui_full | P1 | Start the camera-free Docker demo if Docker is installed |
| runner.docker-stop | Stop Docker Demo | metriplane/runner/allowlist.py | ./tools/docker_stop.sh | web/dashboard/integrations.html | Stop | ui_full | P1 | Stop local MetriPlane Docker demo containers |
| runner.cleanup | Check Stale Processes | metriplane/runner/allowlist.py | _PYTHON tools/ui_safe_cleanup.py | web/dashboard/settings.html; web/dashboard/settings.html | Check stale processes; Run | ui_full | P0 | Runner-safe cleanup check that keeps the active UI stack online |
| api.operator.get.env | Operator GET /env | metriplane/runner/operator_api.py | GET /operator/env | web/dashboard/*.js | GET /operator/env | ui_full | P0 |  |
| api.operator.get.cameras | Operator GET /cameras | metriplane/runner/operator_api.py | GET /operator/cameras | web/dashboard/*.js | GET /operator/cameras | ui_full | P0 |  |
| api.operator.get.profiles | Operator GET /profiles | metriplane/runner/operator_api.py | GET /operator/profiles | web/dashboard/*.js | GET /operator/profiles | ui_full | P1 |  |
| api.operator.get.configs | Operator GET /configs | metriplane/runner/operator_api.py | GET /operator/configs | web/dashboard/*.js | GET /operator/configs | ui_full | P1 |  |
| api.operator.get.latest_run | Operator GET /latest-run | metriplane/runner/operator_api.py | GET /operator/latest-run | web/dashboard/*.js | GET /operator/latest-run | ui_full | P0 |  |
| api.operator.get.runner_status | Operator GET /runner-status | metriplane/runner/operator_api.py | GET /operator/runner-status | web/dashboard/*.js | GET /operator/runner-status | ui_full | P1 |  |
| api.operator.get.live_summary | Operator GET /live-summary | metriplane/runner/operator_api.py | GET /operator/live-summary | web/dashboard/*.js | GET /operator/live-summary | ui_full | P1 |  |
| api.operator.get.objects | Operator GET /objects | metriplane/runner/operator_api.py | GET /operator/objects | web/dashboard/*.js | GET /operator/objects | ui_full | P1 |  |
| api.operator.get.incidents | Operator GET /incidents | metriplane/runner/operator_api.py | GET /operator/incidents | web/dashboard/*.js | GET /operator/incidents | ui_full | P1 |  |
| api.operator.get.traces | Operator GET /traces | metriplane/runner/operator_api.py | GET /operator/traces | web/dashboard/*.js | GET /operator/traces | ui_full | P1 |  |
| api.operator.get.camera_trust | Operator GET /camera-trust | metriplane/runner/operator_api.py | GET /operator/camera-trust | web/dashboard/*.js | GET /operator/camera-trust | ui_full | P1 |  |
| api.operator.get.frames | Operator GET /frames | metriplane/runner/operator_api.py | GET /operator/frames | web/dashboard/*.js | GET /operator/frames | ui_full | P1 |  |
| api.operator.post.create_profile | Operator POST /create-profile | metriplane/runner/operator_api.py | POST /operator/create-profile | web/dashboard/*.js | POST /operator/create-profile | ui_full | P1 |  |
| api.operator.post.write_zones | Operator POST /write-zones | metriplane/runner/operator_api.py | POST /operator/write-zones | web/dashboard/*.js | POST /operator/write-zones | ui_full | P1 |  |
| api.operator.post.save_config | Operator POST /save-config | metriplane/runner/operator_api.py | POST /operator/save-config | web/dashboard/*.js | POST /operator/save-config | ui_full | P1 |  |
| api.operator.post.start_fusion | Operator POST /start-fusion | metriplane/runner/operator_api.py | POST /operator/start-fusion | web/dashboard/*.js | POST /operator/start-fusion | ui_full | P0 |  |
| api.operator.post.calibrate | Operator POST /calibrate | metriplane/runner/operator_api.py | POST /operator/calibrate | web/dashboard/*.js | POST /operator/calibrate | ui_full | P1 |  |
| api.operator.post.validate_alignment | Operator POST /validate-alignment | metriplane/runner/operator_api.py | POST /operator/validate-alignment | web/dashboard/*.js | POST /operator/validate-alignment | ui_full | P1 |  |
| api.operator.post.validate_alignment_full | Operator POST /validate-alignment-full | metriplane/runner/operator_api.py | POST /operator/validate-alignment-full | web/dashboard/*.js | POST /operator/validate-alignment-full | ui_full | P1 |  |
| api.operator.post.generate_report | Operator POST /generate-report | metriplane/runner/operator_api.py | POST /operator/generate-report | web/dashboard/*.js | POST /operator/generate-report | ui_full | P1 |  |
| api.operator.post.checksum | Operator POST /checksum | metriplane/runner/operator_api.py | POST /operator/checksum | web/dashboard/*.js | POST /operator/checksum | ui_full | P1 |  |
| api.operator.post.live_summary | Operator POST /live-summary | metriplane/runner/operator_api.py | POST /operator/live-summary | web/dashboard/*.js | POST /operator/live-summary | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.objects | Operator POST /objects | metriplane/runner/operator_api.py | POST /operator/objects | web/dashboard/*.js | POST /operator/objects | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.incidents | Operator POST /incidents | metriplane/runner/operator_api.py | POST /operator/incidents | web/dashboard/*.js | POST /operator/incidents | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.traces | Operator POST /traces | metriplane/runner/operator_api.py | POST /operator/traces | web/dashboard/*.js | POST /operator/traces | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.camera_trust | Operator POST /camera-trust | metriplane/runner/operator_api.py | POST /operator/camera-trust | web/dashboard/*.js | POST /operator/camera-trust | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.frames | Operator POST /frames | metriplane/runner/operator_api.py | POST /operator/frames | web/dashboard/*.js | POST /operator/frames | ui_full | P1 | Covered by read-only GET fallback for an observe-only endpoint. |
| api.operator.post.ask | Operator POST /ask | metriplane/runner/operator_api.py | POST /operator/ask | web/dashboard/*.js | POST /operator/ask | ui_full | P1 |  |
| api.runner.status | Runner status | metriplane/runner/service.py | GET /status | web/dashboard/*.js | GET /status | ui_full | P0 |  |
| api.runner.commands | Runner action registry | metriplane/runner/service.py | GET /commands | web/dashboard/*.js | GET /commands | ui_full | P1 |  |
| api.runner.jobs | Recent runner jobs | metriplane/runner/service.py | GET /jobs | web/dashboard/*.js | GET /jobs | ui_full | P1 |  |
| api.runner.job_detail | Runner job detail | metriplane/runner/service.py | GET /jobs/<id> | web/dashboard/*.js | GET /jobs/<id> | ui_full | P0 |  |
| api.runner.execute | Execute allowlisted command | metriplane/runner/service.py | POST /execute | web/dashboard/*.js | POST /execute | ui_full | P0 |  |
| api.runner.cancel_job | Cancel running job | metriplane/runner/service.py | POST /jobs/<id>/cancel | web/dashboard/*.js | POST /jobs/<id>/cancel | ui_full | P1 |  |
| tool.ui_safe_cleanup | Ui Safe Cleanup | tools/ui_safe_cleanup.py | python tools/ui_safe_cleanup.py | metriplane/runner/allowlist.py | runner action | ui_full | P1 | Covered by a runner allowlist command. |

## Stable Features Partially Available

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cli.ask | metriplane ask | metriplane/cli.py | python -m metriplane.cli ask | web/dashboard/* | python -m metriplane.cli ask | ui_partial | P1 |  |
| cli.atlas | metriplane atlas | metriplane/cli.py | python -m metriplane.cli atlas | web/dashboard/* | python -m metriplane.cli atlas | ui_partial | P1 |  |
| cli.camera-trust | metriplane camera-trust | metriplane/cli.py | python -m metriplane.cli camera-trust | web/dashboard/* | python -m metriplane.cli camera-trust | ui_partial | P1 |  |
| cli.cleanup | metriplane cleanup | metriplane/cli.py | python -m metriplane.cli cleanup | web/dashboard/* | python -m metriplane.cli cleanup | ui_partial | P0 |  |
| cli.command-center | metriplane command-center | metriplane/cli.py | python -m metriplane.cli command-center | web/dashboard/* | python -m metriplane.cli command-center | ui_partial | P1 |  |
| cli.incidents | metriplane incidents | metriplane/cli.py | python -m metriplane.cli incidents | web/dashboard/* | python -m metriplane.cli incidents | ui_partial | P2 |  |
| cli.objects | metriplane objects | metriplane/cli.py | python -m metriplane.cli objects | web/dashboard/* | python -m metriplane.cli objects | ui_partial | P2 |  |
| cli.query | metriplane query | metriplane/cli.py | python -m metriplane.cli query | web/dashboard/* | python -m metriplane.cli query | ui_partial | P2 |  |
| cli.replay | metriplane replay | metriplane/cli.py | python -m metriplane.cli replay | web/dashboard/* | python -m metriplane.cli replay | ui_partial | P1 |  |
| cli.rules | metriplane rules | metriplane/cli.py | python -m metriplane.cli rules | web/dashboard/* | python -m metriplane.cli rules | ui_partial | P2 |  |
| cli.sentinel | metriplane sentinel | metriplane/cli.py | python -m metriplane.cli sentinel | web/dashboard/* | python -m metriplane.cli sentinel | ui_partial | P1 |  |
| cli.start | metriplane start | metriplane/cli.py | python -m metriplane.cli start | web/dashboard/* | python -m metriplane.cli start | ui_partial | P0 |  |
| cli.status | metriplane status | metriplane/cli.py | python -m metriplane.cli status | web/dashboard/* | python -m metriplane.cli status | ui_partial | P0 |  |
| cli.stop | metriplane stop | metriplane/cli.py | python -m metriplane.cli stop | web/dashboard/* | python -m metriplane.cli stop | ui_partial | P0 |  |
| cli.test | metriplane test | metriplane/cli.py | python -m metriplane.cli test | web/dashboard/* | python -m metriplane.cli test | ui_partial | P2 |  |
| cli.traces | metriplane traces | metriplane/cli.py | python -m metriplane.cli traces | web/dashboard/* | python -m metriplane.cli traces | ui_partial | P1 |  |
| cli.doctor | metriplane doctor | metriplane/cli.py | python -m metriplane.cli doctor | web/dashboard/* | cli.py | ui_copy_command_only | P0 |  |
| tool.analyze_id_stability_jsonl | Analyze Id Stability Jsonl | tools/analyze_id_stability_jsonl.py | python tools/analyze_id_stability_jsonl.py | web/dashboard/* | analyze_id_stability_jsonl.py | ui_copy_command_only | P2 |  |
| tool.calibrate_intrinsics_chessboard | Calibrate Intrinsics Chessboard | tools/calibrate_intrinsics_chessboard.py | python tools/calibrate_intrinsics_chessboard.py | web/dashboard/* | calibrate_intrinsics_chessboard.py | ui_copy_command_only | P2 |  |
| tool.calibrate_planar_homography | Calibrate Planar Homography | tools/calibrate_planar_homography.py | python tools/calibrate_planar_homography.py | web/dashboard/* | calibrate_planar_homography.py | ui_copy_command_only | P2 |  |
| tool.debug_alignment | Debug Alignment | tools/debug_alignment.py | python tools/debug_alignment.py | web/dashboard/* | debug_alignment.py | ui_copy_command_only | P2 |  |
| tool.list_cameras | List Cameras | tools/list_cameras.py | python tools/list_cameras.py | web/dashboard/* | list_cameras.py | ui_copy_command_only | P1 |  |
| tool.report_alignment | Report Alignment | tools/report_alignment.py | python tools/report_alignment.py | web/dashboard/* | report_alignment.py | ui_copy_command_only | P2 |  |
| tool.run_ui_demo_replay | Run Ui Demo Replay | tools/run_ui_demo_replay.py | python tools/run_ui_demo_replay.py | web/dashboard/* | run_ui_demo_replay.py | ui_copy_command_only | P1 |  |
| tool.zones_report_jsonl | Zones Report Jsonl | tools/zones_report_jsonl.py | python tools/zones_report_jsonl.py | web/dashboard/* | zones_report_jsonl.py | ui_copy_command_only | P2 |  |
| tool.command_center_up | Command Center Up | tools/command_center_up.sh | tools/command_center_up.sh | web/dashboard/* | command_center_up.sh | ui_copy_command_only | P2 |  |
| tool.dashboard_runner | Dashboard Runner | tools/dashboard_runner.sh | tools/dashboard_runner.sh | web/dashboard/* | dashboard_runner.sh | ui_copy_command_only | P2 |  |
| tool.mp | Mp | tools/mp.sh | tools/mp.sh | web/dashboard/* | mp.sh | ui_copy_command_only | P2 |  |

## Stable Features Missing From UI

No missing stable features found.

## CLI-Only Features With Documented Reason

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| runner.health-degrade-cam1 | Health Degradation | metriplane/runner/allowlist.py | ./tools/mp.sh health-degrade-cam1 | - | - | cli_only_documented | P1 | Requires second capture-capable camera |
| runner.gpu-equivalence | GPU Equivalence Test | metriplane/runner/allowlist.py | ./tools/mp.sh gpu-equivalence | - | - | cli_only_documented | P1 | Requires visible ArUco markers in test session |
| runner.run-fusion | Run Fusion | metriplane/runner/allowlist.py | ./tools/mp.sh run-fusion cpu 60 test | - | - | cli_only_documented | P1 | Hardware/configuration dependent - use CLI directly |
| cli.contracts | metriplane contracts | metriplane/cli.py | python -m metriplane.cli contracts | - | - | cli_only_documented | P2 | Lower-level CLI surface; keep in Help/advanced docs. |
| cli.counterfactual | metriplane counterfactual | metriplane/cli.py | python -m metriplane.cli counterfactual | - | - | cli_only_documented | P2 | Lower-level CLI surface; keep in Help/advanced docs. |
| cli.restart | metriplane restart | metriplane/cli.py | python -m metriplane.cli restart | - | - | cli_only_documented | P2 | Lower-level CLI surface; keep in Help/advanced docs. |
| tool.analyze_session_metrics | Analyze Session Metrics | tools/analyze_session_metrics.py | python tools/analyze_session_metrics.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.audit_ui_functionality | Audit Ui Functionality | tools/audit_ui_functionality.py | python tools/audit_ui_functionality.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.check_ros2_adapters | Check Ros2 Adapters | tools/check_ros2_adapters.py | python tools/check_ros2_adapters.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.plot_compute_backend_comparison | Plot Compute Backend Comparison | tools/plot_compute_backend_comparison.py | python tools/plot_compute_backend_comparison.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.preview_world_overlay | Preview World Overlay | tools/preview_world_overlay.py | python tools/preview_world_overlay.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.preview_world_overlay_multi | Preview World Overlay Multi | tools/preview_world_overlay_multi.py | python tools/preview_world_overlay_multi.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.preview_world_overlay_multi_ws | Preview World Overlay Multi Ws | tools/preview_world_overlay_multi_ws.py | python tools/preview_world_overlay_multi_ws.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.preview_zones_overlay | Preview Zones Overlay | tools/preview_zones_overlay.py | python tools/preview_zones_overlay.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.run_fusion_preview | Run Fusion Preview | tools/run_fusion_preview.py | python tools/run_fusion_preview.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.run_fusion_yaml | Run Fusion Yaml | tools/run_fusion_yaml.py | python tools/run_fusion_yaml.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.run_live_yaml | Run Live Yaml | tools/run_live_yaml.py | python tools/run_live_yaml.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.run_ui_timing_check | Run Ui Timing Check | tools/run_ui_timing_check.py | python tools/run_ui_timing_check.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.session_health_summary | Session Health Summary | tools/session_health_summary.py | python tools/session_health_summary.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.ws_replay_jsonl | Ws Replay Jsonl | tools/ws_replay_jsonl.py | python tools/ws_replay_jsonl.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.ws_smoke_client | Ws Smoke Client | tools/ws_smoke_client.py | python tools/ws_smoke_client.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.ws_viewer_multi | Ws Viewer Multi | tools/ws_viewer_multi.py | python tools/ws_viewer_multi.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.demo4_everything | Demo4 Everything | tools/demo4_everything.sh | tools/demo4_everything.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_clean | Docker Clean | tools/docker_clean.sh | tools/docker_clean.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_demo_up | Docker Demo Up | tools/docker_demo_up.sh | tools/docker_demo_up.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_dummy_up | Docker Dummy Up | tools/docker_dummy_up.sh | tools/docker_dummy_up.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_live_up | Docker Live Up | tools/docker_live_up.sh | tools/docker_live_up.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_smoke_test | Docker Smoke Test | tools/docker_smoke_test.sh | tools/docker_smoke_test.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.docker_stop | Docker Stop | tools/docker_stop.sh | tools/docker_stop.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.jetson_preflight | Jetson Preflight | tools/jetson_preflight.sh | tools/jetson_preflight.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.proof_m8_fusion | Proof M8 Fusion | tools/proof_m8_fusion.sh | tools/proof_m8_fusion.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.run_demo_all | Run Demo All | tools/run_demo_all.sh | tools/run_demo_all.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.start_metriplane | Start Metriplane | tools/start_metriplane.sh | tools/start_metriplane.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.validate-replay | Validate Replay | tools/validate-replay.sh | tools/validate-replay.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.verify_m1_m6 | Verify M1 M6 | tools/verify_m1_m6.sh | tools/verify_m1_m6.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| tool.verify_m6_offline | Verify M6 Offline | tools/verify_m6_offline.sh | tools/verify_m6_offline.sh | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.edge_latency | Edge Latency | benchmarks/edge_latency.py | python benchmarks/edge_latency.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.event_throughput | Event Throughput | benchmarks/event_throughput.py | python benchmarks/event_throughput.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.gpu_batch_replay | Gpu Batch Replay | benchmarks/gpu_batch_replay.py | python benchmarks/gpu_batch_replay.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.gpu_fusion_scaling | Gpu Fusion Scaling | benchmarks/gpu_fusion_scaling.py | python benchmarks/gpu_fusion_scaling.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_backpressure | Run Backpressure | benchmarks/run_backpressure.py | python benchmarks/run_backpressure.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_compute_backend_comparison | Run Compute Backend Comparison | benchmarks/run_compute_backend_comparison.py | python benchmarks/run_compute_backend_comparison.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_compute_equivalence | Run Compute Equivalence | benchmarks/run_compute_equivalence.py | python benchmarks/run_compute_equivalence.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_fusion_jitter | Run Fusion Jitter | benchmarks/run_fusion_jitter.py | python benchmarks/run_fusion_jitter.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_latency_breakdown | Run Latency Breakdown | benchmarks/run_latency_breakdown.py | python benchmarks/run_latency_breakdown.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_mapping_error | Run Mapping Error | benchmarks/run_mapping_error.py | python benchmarks/run_mapping_error.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |
| benchmark.run_replay_determinism | Run Replay Determinism | benchmarks/run_replay_determinism.py | python benchmarks/run_replay_determinism.py | - | - | cli_only_documented | P2 | Developer/diagnostic script; not a primary localhost workflow. |

## Disabled Or Integration Features With Reasons

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Broken Or Dead UI Actions

Broken button count is reported in the summary. A broken button is any `data-command-id` not present in the runner allowlist.

## UI Hardening Checks

- `duplicate_html_ids` counts repeated `id` attributes within the same HTML file.
- `js_syntax_errors` comes from `node --check` over dashboard JavaScript files.
- `buttons_with_duplicate_command_id_on_same_card` flags accidental duplicate run buttons in one card.
- `data_needs_atlas_buttons_never_enabled` flags Atlas-gated buttons missing the enable path.
- `read_only_fallback_endpoints` reports observe-only POST endpoints considered covered by GET UI calls.

## Recommendations

- Keep all runnable dashboard buttons backed by `metriplane/runner/allowlist.py`.
- Keep hardware-dependent workflows visible, but gated with dependency checks and clear reasons.
- Treat unresolved P0/P1 `ui_missing` rows as release blockers.
