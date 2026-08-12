<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# External evaluator packet

This packet is for a person independently checking one exact, bounded proof.
No meeting is required. Choose either Evaluation A or Evaluation B, preserve
the first meaningful failure, and report what you observed with
[`evaluator-report-template.md`](evaluator-report-template.md).

This candidate is not yet published. Do not evaluate a proposed tag until it
exists and resolves. For final external evidence, use only the immutable
`maniskill-pickcube-proof-v1` tag, confirm its 40-character commit against
`proof-record.json`, and record both. A pull-request-head run is candidate
feedback, not a stable tagged reproduction.

## What is being checked

The proof uses 75 complete, position-only planar frames derived from one pinned
official ManiSkill `PickCube-v1` demonstration episode. The incident and
control share byte-identical normalized state and target geometry. They differ
in one operator-authored relative wait: `0.20 s` produces the recorded
incident, while `0.30 s` produces the recorded control.

This is not a request to validate official PickCube success or failure, a
grasp, 3D placement, orientation, physical accuracy, simulator realism,
robot safety, or production readiness. Read [`CLAIMS.md`](CLAIMS.md) before
describing the result publicly.

## Evaluation rules

- PASS and FAIL are equally useful. Report the observed result accurately.
- No praise, endorsement, GitHub star, positive review, or predetermined
  conclusion is requested.
- Do not change the source, episode, normalized state, entity mapping, target
  polygon, `0.20` / `0.30 s` waits, process rules, or expected counts to force
  a pass.
- Do not supply `expected-outcome.json` to Atlas. It is test metadata, not an
  input.
- Preserve the first meaningful failed command and its complete output before
  attempting a workaround.
- Report every maintainer instruction or intervention required beyond the
  public packet.
- Do not hide a negative or confusing result. If you later resolve it, report
  both the original failure and the resolution.
- Do not include secrets, usernames, home-directory paths, or private source
  material in a public report. Redact only private identifiers, and state what
  was redacted.
- State whether the evaluation was compensated. Compensation does not
  invalidate a technical result, but it must not be hidden.
- Choose your preferred attribution and quotation permissions. Anonymous or
  private feedback is accepted, but it cannot be represented as attributable
  public independent evidence.

## Evaluation A — Portable rerun

Expected time: approximately **15–30 minutes after environment setup**.

Prerequisites:

- Linux or macOS on a recorded architecture;
- CPython 3.12 or 3.13;
- Git and ordinary wheel-build/install tooling;
- enough local space for a source checkout, clean environments, and outputs.

You do **not** need ManiSkill, SAPIEN, Torch, h5py, Vulkan, the isolated
adapter, raw HDF5/JSON, or robot assets.

Required actions:

1. Clone the public repository and check out the exact immutable proof tag.
2. Record `git rev-parse HEAD`, verify it against `proof-record.json`, and
   require a clean tree.
3. Build the wheel from that exact revision.
4. Install the wheel and declared runtime dependencies into a fresh environment
   outside the checkout. Do not install the published PyPI/conda v0.3.0 package
   as a substitute: it lacks the proof commands.
5. Set `METRIPLANE_GIT_COMMIT` to the exact 40-character proof commit.
6. Run the Level-A wrapper with a new output root:

   ```bash
   python proofs/maniskill-pickcube-v1/reproduce.py \
     --repo-root . \
     --out ../maniskill-proof-reproduction \
     --metriplane-commit FULL_PROOF_COMMIT \
     --metriplane-command PATH_TO_FRESH_ENV_METRIPLANE
   ```

7. Preserve `reproduction-result.json` and the console output.
8. Confirm the observed incident and control counts, incident evidence
   verification, regression result, lack of control artifacts, and path-
   portability result.
9. Move the output directory and, if directed by the wrapper, recheck contained
   report/dashboard/USDA/evidence/regression artifacts from the moved location.
10. Complete the report template, including the first failed command or first
    confusing term even if the final result passes.

Expected bounded result:

| Fixture | Frames | Events | Deviations | Incidents | Incident-derived artifacts |
| --- | ---: | ---: | ---: | ---: | --- |
| Incident | 75 | 4 | 1 | 1 | Evidence verifies; generated regression passes |
| Control | 75 | 3 | 0 | 0 | No evidence bundle and no regression |

The wrapper returning nonzero is a valid FAIL report. Do not rerun after
editing an input or expectation.

## Evaluation B — Full source conversion

Expected time: approximately **1–3 hours after prerequisites are available**,
with additional time possible for the first dependency installation, pinned
dataset download, or software-Vulkan setup. Report actual elapsed and active
setup time rather than relying on this estimate.

Prerequisites:

- Linux x86_64;
- CPython 3.12 and `uv 0.12.0`, the version used for the recorded MET-15
  conversion environment;
- network access to the exact pinned dataset revision and package artifacts;
- storage for the 36,590,010-byte ZIP, extracted source, three clean
  conversions, and environments;
- the pinned ManiSkill 3.0.1 environment, SAPIEN, Torch, h5py, and adapter;
- a Vulkan implementation, potentially a software Vulkan device, for upstream
  scene construction even though conversion does not render.

Required actions:

1. Complete the exact tag/commit identity checks used in Evaluation A.
2. Restore the isolated adapter environment from its frozen dependency lock.
3. Acquire the immutable source revision with the public adapter command.
4. Verify the ZIP, HDF5, and JSON byte sizes and SHA-256 values before use.
5. Inspect episode `0` / `traj_0` and require 74 transitions, 75 stored states,
   and independent named-API restoration of all 75 states.
6. Record the copied ZIP, HDF5, and JSON hashes before conversion.
7. Convert three separate, empty roots with public adapter commit
   `95d1134d9fb9273318c552c507952f1c5c26877e` and the frozen configuration.
8. Run `finalize-equivalence` across the three named roots.
9. Compare the finalized outputs byte-for-byte with both exact tagged fixture
   trees and confirm the recorded fixture fingerprints.
10. Recompute the copied ZIP, HDF5, and JSON hashes and confirm that conversion
    did not modify any source file.
11. Complete the report template and attach the machine-readable acquisition,
    inspection, conversion, and equivalence results as permitted.

Follow the complete command sequence in
[`REPRODUCE.md`](REPRODUCE.md#level-b--full-source-to-fixture-conversion).
Do not publish or redistribute upstream raw source files or simulator assets as
part of your report.

Evaluation B audits the conversion provenance. It does not establish physical
accuracy, official PickCube outcome, simulator realism, or general ManiSkill
compatibility.

## Report contents

Use [`evaluator-report-template.md`](evaluator-report-template.md) without
deleting fields. Include:

- an attributable identifier and organization only if voluntarily provided;
- country, OS, architecture, Python, exact tag/commit, and installation method;
- Evaluation A or B;
- the first failed command and first confusing term;
- elapsed setup/evaluation time and maintainer assistance;
- validation, incident/control counts, evidence, regression, and path results;
- discrepancies and any later resolution;
- public attribution, quotation, and privacy choices; and
- compensation or no-compensation declaration.

Independent evidence exists only after an outside person actually performs the
work. The owner-authored packet, its CI, and its representative artifacts are
not substitutes for that action.
