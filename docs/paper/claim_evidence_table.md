<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# v0.2.0 Claim Evidence Table

| Claim | Status | Evidence | Boundary |
|---|---|---|---|
| v0.2.0 is the current public DOI-archived release and main SoftwareX paper artifact | Supported | `README.md`, `ARTIFACTS.md`, `docs/paper/reproduction.md`, DOI `10.5281/zenodo.20736619`, Zenodo record `https://zenodo.org/records/20736619` | SoftwareX acceptance or peer review is not claimed. |
| v0.1.4 is the historical DOI-archived baseline | Supported | `README.md`, `ARTIFACTS.md`, DOI `10.5281/zenodo.20631037` | Do not describe v0.1.4 as the v0.2.0 artifact. |
| Automated release gate passes locally | Supported | `evidence/paper_v2_0/test_output.txt` | Captured result is 580/580 tests in the local environment. |
| Deterministic replay is reproducible on the checked-in demo session | Supported | `evidence/paper_v2_0/logs/deterministic_replay.txt`, `evidence/paper_v2_0/runs/demo-evidence/replay_determinism.csv` | Checked-in demo replay only; no live-camera claim. |
| Assembly-cell Evidence Review produces the paper artifacts | Supported | `evidence/paper_v2_0/atlas_run/` | One deterministic assembly-cell domain pack and replay. |
| Cell Truth Report summarizes one missing-tool delay incident | Supported | `evidence/paper_v2_0/atlas_run/cell_truth_report.md`, `.html` | Derived from replayed planar state, not raw-video judgement. |
| Evidence bundle `INC-0001.zip` is portable and verifies | Supported | `evidence/paper_v2_0/logs/bundle_verify.txt`, `evidence/paper_v2_0/artifacts/INC-0001_zip_listing.txt`, `evidence/paper_v2_0/artifacts/INC-0001_zip.sha256` | Local checksum/content verification, not malware scanning. |
| Generated physical regression test passes | Supported | `evidence/paper_v2_0/logs/regression_test.json`, `evidence/paper_v2_0/atlas_run/regression_tests/INC-0001.yaml` | Regression covers the generated incident expectation. |
| Python distributions build and validate | Supported | `evidence/paper_v2_0/logs/13_python_build.txt`, `evidence/paper_v2_0/logs/14_twine_check.txt`, `evidence/paper_v2_0/artifacts/dist_checksums.sha256` | Distribution files are generated locally under `dist/`; do not add `dist/` to git. |
| Sentinel and Atlas are observe-only | Supported | `docs/release_v0_2_claims.md`, `docs/atlas/README.md`, `ARTIFACTS.md` | No robot or machine control claim. |
| Dashboard build completes | Supported | `evidence/paper_v2_0/logs/09_dashboard_build.txt` | Static dashboard artifact generation only; not a browser-runtime benchmark. |
| Docker local replay/demo smoke was captured | Supported as bounded smoke only | `evidence/paper_v2_0/logs/16_docker_demo_up.txt`, `evidence/paper_v2_0/logs/17_docker_health.json`, `evidence/paper_v2_0/logs/18_docker_clean.txt` | Build/start, health endpoint JSON, and cleanup only. Not benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence. |
| Integration adapters exist | Supported with limits | `docs/release_v0_2_claims.md`, integration docs and evidence files | Isaac Sim remains NOT RUN; Docker is bounded to local replay/demo smoke; ROS 2/Omniverse claims remain bounded to existing manual/export evidence. |

## Explicit Non-Claims

- No safety certification.
- No robot or machine control.
- No marker-free tracking.
- No production collision avoidance.
- No quality-release approval.
- No full 3D reconstruction.
- No Docker benchmark, production-runtime, live-camera, replay-mode, reliability, or safety evidence in this package.
- No Isaac Sim runtime evidence in this package.
