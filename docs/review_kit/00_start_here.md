<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Review Kit Start Here

This review kit provides a camera-free path through the archived Metriplane
`v0.2.0` SoftwareX artifact. The core path uses the exact tag and writes rerun
outputs to temporary directories. The checked-in author-run evidence remains
unchanged under `evidence/paper_v2_0/`.

Recommended order:

1. Install the exact tag with `docs/review_kit/01_install.md`.
2. Run deterministic replay with `docs/review_kit/02_run_deterministic_replay.md`.
3. Run the assembly-cell case with `docs/review_kit/03_run_assembly_cell_case.md`.
4. Verify the evidence bundle with `docs/review_kit/04_verify_evidence_bundle.md`.
5. Run the generated regression check with `docs/review_kit/05_run_regression_test.md`.
6. Compare expected outputs with `docs/review_kit/06_expected_outputs.md`.
7. Use `docs/review_kit/07_review_questions.md` for review prompts.
8. Read `docs/review_kit/08_known_limitations.md` for claim boundaries.
9. Run the separate optional maintainer gate with `docs/review_kit/09_full_maintainer_gate.md`.

The core artifact path does not require Playwright or Chromium. The artifact is
observe-only and replay-based. It does not control machines, certify safety,
approve quality release, or claim marker-free tracking.
