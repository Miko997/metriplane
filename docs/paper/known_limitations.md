<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# v0.2.0 Known Limitations

MetriPlane v0.2.0 is scoped to calibrated planar XY state with tracked/tagged
assets. The paper evidence package is intentionally camera-free and replay
based so reviewers can reproduce it without hardware.

- The local workflows are observe-only. They do not actuate robots or machines.
- The software is not a certified safety system and does not approve quality release.
- The tracking identity source is fiducial/tagged assets. No marker-free tracking claim is made.
- The Atlas assembly-cell evidence covers one checked-in deterministic replay and one domain pack.
- The Cell Truth Report is derived from replayed planar state, not raw video judgement.
- The deterministic replay evidence uses a small checked-in demo session for this package.
- Docker dummy-mode local smoke was captured after the package was created: build/start, health endpoint JSON, and cleanup logs. This is bounded smoke evidence only and is not promoted as benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence.
- Isaac Sim runtime was not run for this package.
- Existing ROS 2 runtime evidence is a one-maintainer-environment smoke, not a latency or production-runtime claim.
- Existing Omniverse evidence is partial unless a raw simulator-open log or screenshot is added.
- The package build and `twine check` pass after adding release metadata; distribution files are generated locally under `dist/` and should not be added to git.
- The v0.2.0 branch remains a release candidate until the GitHub tag and Zenodo archive are created.
