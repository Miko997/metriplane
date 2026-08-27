<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# UI Missing Features Report

Generated deterministically by `python tools/audit_ui_functionality.py --write`.

Canonical projection SHA-256: `03515a6439949263d67d6783187ff0b435f004ac3aba2f6b70315eded3f47667`

- Missing features total: `8`
- Release-blocking P0/P1 coverage rows: `11`

## Release-Blocking P0/P1 Coverage

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cli.ask | metriplane ask | metriplane/cli.py | python -m metriplane.cli ask | - | - | ui_missing | P1 |  |
| cli.camera-trust | metriplane camera-trust | metriplane/cli.py | python -m metriplane.cli camera-trust | - | - | ui_missing | P1 |  |
| cli.cleanup | metriplane cleanup | metriplane/cli.py | python -m metriplane.cli cleanup | - | - | ui_missing | P0 |  |
| cli.command-center | metriplane command-center | metriplane/cli.py | python -m metriplane.cli command-center | - | - | ui_missing | P1 |  |
| cli.replay | metriplane replay | metriplane/cli.py | python -m metriplane.cli replay | - | - | ui_missing | P1 |  |
| cli.start | metriplane start | metriplane/cli.py | python -m metriplane.cli start | web/dashboard/* | python -m metriplane.cli start | ui_copy_command_only | P0 |  |
| cli.status | metriplane status | metriplane/cli.py | python -m metriplane.cli status | - | - | ui_missing | P0 |  |
| cli.stop | metriplane stop | metriplane/cli.py | python -m metriplane.cli stop | - | - | ui_missing | P0 |  |
| cli.traces | metriplane traces | metriplane/cli.py | python -m metriplane.cli traces | - | - | ui_missing | P1 |  |
| tool.list_cameras | List Cameras | tools/list_cameras.py | python tools/list_cameras.py | web/dashboard/* | list_cameras.py | ui_copy_command_only | P1 |  |
| tool.run_ui_demo_replay | Run Ui Demo Replay | tools/run_ui_demo_replay.py | python tools/run_ui_demo_replay.py | web/dashboard/* | run_ui_demo_replay.py | ui_copy_command_only | P1 |  |

## Missing Features

| action_id | feature_name | source_path | command_or_endpoint | ui_route | ui_label | coverage_status | risk | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
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
