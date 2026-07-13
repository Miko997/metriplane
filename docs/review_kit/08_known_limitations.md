<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Review Kit Known Limitations

- The core review path is camera-free and replay-based.
- The assembly-cell case covers one checked-in deterministic scenario.
- The evidence is planar XY and depends on tracked or tagged assets.
- The software is observe-only and does not control robots or machines.
- The software is not safety-certified and does not approve quality release.
- No marker-free tracking claim is made.
- Bundle verification establishes local archive structure and integrity, not physical source-state correctness.
- The generated regression check is limited to selected expected fields for the preserved replay condition.
- The full maintainer gate requires separate pytest, Playwright, Chromium, and system-dependency installation.
- Existing ROS 2, Omniverse, Docker, and simulator evidence remains bounded to its documented scope.
- The author-run evidence was captured at pre-release commit `44bed6d85786675c5581154f588a7ad2529c85d6` and included unchanged in tag `v0.2.0`.
