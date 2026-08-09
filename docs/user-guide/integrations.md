<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Integrations and actual support status

The v0.3.0 adoption path is intentionally narrow: install the Python package,
analyze a `FrameStateModel` JSONL recording with process rules, inspect the local
report, verify its bundle, and rerun its generated regression check.

| Path | v0.3.0 status | What that means |
| --- | --- | --- |
| Bundled camera-free demo | Release-gated | Runs from an installed wheel outside a source checkout on Ubuntu and macOS with Python 3.12/3.13. |
| `FrameStateModel` JSONL + process rules | Supported incident input | Requires already-estimated object IDs, positions, and preclassified zone labels. |
| Headless/SSH use | Supported for the demo | Omit `--open`; all artifacts are still generated locally. |
| Live camera runtime | Optional, Linux-hardware dependent | Not needed for the demo. A missing camera does not make the camera-free installation broken. No macOS live-camera claim is made. |
| GPU acceleration | Optional | Not needed for the demo or recorded incident path. CPU operation is the default adoption path. |
| ROS 2 source bridge | Repository-only, separate component | It is not part of the core wheel or the v0.3.0 product promise. It does not add rosbag ingestion. |
| rosbag / rosbag2 / MCAP import | Not implemented for v0.3.0 | Convert upstream data to validated `FrameStateModel` JSONL yourself; no generic importer is claimed. |
| Raw-video incident import | Not implemented for v0.3.0 | This workflow starts after object-state estimation and zone classification. |
| USD / Isaac Sim replay export | Experimental, manual external validation | Repository tools exist, but Isaac Sim is not required and end-to-end rendering is not a v0.3.0 gate. |
| WSL2 | Not advertised | No clean manual v0.3.0 candidate run is recorded yet. Archived v0.2.0 instructions are not a current support claim. |
| Native Windows | Unsupported | It is neither tested nor advertised. |

The authoritative platform matrix is
[Supported Environments](https://github.com/Miko997/metriplane/blob/main/docs/SUPPORTED_ENVIRONMENTS.md).
The larger
[integration reference](https://github.com/Miko997/metriplane/blob/main/docs/INTEGRATIONS.md)
describes source-tree interfaces and experimental components; its presence does
not broaden the installed-demo support statement above.

Metriplane outputs are observe-only. An integration may read its events and
artifacts, but Metriplane does not send robot commands, stop equipment, or make a
safety or quality-release decision.
