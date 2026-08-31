<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Missing Features Report

Generated deterministically by `python tools/audit_ui_functionality.py --write`.

Canonical projection SHA-256: `922efd3be3c49255cc1b52d27f473f6f4351dfa0912c9c13dd185dfe4b7359bf`

- Missing features total: `14`
- Release-blocking P0/P1 coverage rows: `19`

## Release-Blocking P0/P1 Coverage

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| api.operator.post.camera_trust | Operator POST /camera-trust | metriplane/runner/operator_api.py | POST /operator/camera-trust | - | - | ui_missing | P1 |  |
| api.operator.post.frames | Operator POST /frames | metriplane/runner/operator_api.py | POST /operator/frames | - | - | ui_missing | P1 |  |
| api.operator.post.incidents | Operator POST /incidents | metriplane/runner/operator_api.py | POST /operator/incidents | - | - | ui_missing | P1 |  |
| api.operator.post.live_summary | Operator POST /live-summary | metriplane/runner/operator_api.py | POST /operator/live-summary | - | - | ui_missing | P1 |  |
| api.operator.post.objects | Operator POST /objects | metriplane/runner/operator_api.py | POST /operator/objects | - | - | ui_missing | P1 |  |
| api.operator.post.traces | Operator POST /traces | metriplane/runner/operator_api.py | POST /operator/traces | - | - | ui_missing | P1 |  |
| cli.ask | metriplane ask | metriplane/cli.py | python -m metriplane.cli ask | - | - | ui_missing | P1 |  |
| cli.atlas | metriplane atlas | metriplane/cli.py | python -m metriplane.cli atlas | metriplane/runner/allowlist.py | dashboard-covered CLI subcommand | ui_partial | P1 | One or more subcommands are exposed; the root command is not full UI coverage. |
| cli.camera-trust | metriplane camera-trust | metriplane/cli.py | python -m metriplane.cli camera-trust | - | - | ui_missing | P1 |  |
| cli.cleanup | metriplane cleanup | metriplane/cli.py | python -m metriplane.cli cleanup | - | - | ui_missing | P0 |  |
| cli.command-center | metriplane command-center | metriplane/cli.py | python -m metriplane.cli command-center | - | - | ui_missing | P1 |  |
| cli.replay | metriplane replay | metriplane/cli.py | python -m metriplane.cli replay | - | - | ui_missing | P1 |  |
| cli.sentinel | metriplane sentinel | metriplane/cli.py | python -m metriplane.cli sentinel | metriplane/runner/allowlist.py | dashboard-covered CLI subcommand | ui_partial | P1 | One or more subcommands are exposed; the root command is not full UI coverage. |
| cli.start | metriplane start | metriplane/cli.py | python -m metriplane.cli start | web/dashboard/* | python -m metriplane.cli start | ui_copy_command_only | P0 |  |
| cli.status | metriplane status | metriplane/cli.py | python -m metriplane.cli status | - | - | ui_missing | P0 |  |
| cli.stop | metriplane stop | metriplane/cli.py | python -m metriplane.cli stop | - | - | ui_missing | P0 |  |
| cli.traces | metriplane traces | metriplane/cli.py | python -m metriplane.cli traces | - | - | ui_missing | P1 |  |
| tool.list_cameras | List Cameras | tools/list_cameras.py | python tools/list_cameras.py | web/dashboard/* | list_cameras.py | ui_copy_command_only | P1 |  |
| tool.run_ui_demo_replay | Run Ui Demo Replay | tools/run_ui_demo_replay.py | python tools/run_ui_demo_replay.py | web/dashboard/* | run_ui_demo_replay.py | ui_copy_command_only | P1 |  |

## Missing Features

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| api.operator.post.camera_trust | Operator POST /camera-trust | metriplane/runner/operator_api.py | POST /operator/camera-trust | - | - | ui_missing | P1 |  |
| api.operator.post.frames | Operator POST /frames | metriplane/runner/operator_api.py | POST /operator/frames | - | - | ui_missing | P1 |  |
| api.operator.post.incidents | Operator POST /incidents | metriplane/runner/operator_api.py | POST /operator/incidents | - | - | ui_missing | P1 |  |
| api.operator.post.live_summary | Operator POST /live-summary | metriplane/runner/operator_api.py | POST /operator/live-summary | - | - | ui_missing | P1 |  |
| api.operator.post.objects | Operator POST /objects | metriplane/runner/operator_api.py | POST /operator/objects | - | - | ui_missing | P1 |  |
| api.operator.post.traces | Operator POST /traces | metriplane/runner/operator_api.py | POST /operator/traces | - | - | ui_missing | P1 |  |
| cli.ask | metriplane ask | metriplane/cli.py | python -m metriplane.cli ask | - | - | ui_missing | P1 |  |
| cli.camera-trust | metriplane camera-trust | metriplane/cli.py | python -m metriplane.cli camera-trust | - | - | ui_missing | P1 |  |
| cli.cleanup | metriplane cleanup | metriplane/cli.py | python -m metriplane.cli cleanup | - | - | ui_missing | P0 |  |
| cli.command-center | metriplane command-center | metriplane/cli.py | python -m metriplane.cli command-center | - | - | ui_missing | P1 |  |
| cli.replay | metriplane replay | metriplane/cli.py | python -m metriplane.cli replay | - | - | ui_missing | P1 |  |
| cli.status | metriplane status | metriplane/cli.py | python -m metriplane.cli status | - | - | ui_missing | P0 |  |
| cli.stop | metriplane stop | metriplane/cli.py | python -m metriplane.cli stop | - | - | ui_missing | P0 |  |
| cli.traces | metriplane traces | metriplane/cli.py | python -m metriplane.cli traces | - | - | ui_missing | P1 |  |

## First-Pass Rule

P0/P1 rows should become `ui_full`, `ui_disabled_with_reason`, or `cli_only_documented` before the unified UI is considered release-ready.
