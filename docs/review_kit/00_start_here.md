<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Review Kit Start Here

This review kit gives a camera-free path through the v0.2.0 SoftwareX paper
artifact. Start with the checked-in evidence package at `evidence/paper_v2_0/`,
then rerun the commands if you want to verify the outputs locally.

Recommended order:

1. Install the package with `docs/review_kit/01_install.md`.
2. Run deterministic replay with `docs/review_kit/02_run_deterministic_replay.md`.
3. Run the assembly-cell case with `docs/review_kit/03_run_assembly_cell_case.md`.
4. Verify the evidence bundle with `docs/review_kit/04_verify_evidence_bundle.md`.
5. Run the generated regression test with `docs/review_kit/05_run_regression_test.md`.
6. Compare expected outputs with `docs/review_kit/06_expected_outputs.md`.
7. Use `docs/review_kit/07_review_questions.md` for review prompts.
8. Read `docs/review_kit/08_known_limitations.md` for claim boundaries.

The artifact is observe-only and replay-based. It does not control machines,
certify safety, approve quality release, or claim marker-free tracking.
