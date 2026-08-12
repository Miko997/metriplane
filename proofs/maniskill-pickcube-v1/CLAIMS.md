<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# Claims register

This register bounds every public statement about proof version `1`. Its
evidence classification is
`owner_generated_public_technical_proof`. Independent reproduction is `false`
until an outside person actually performs and reports an evaluation.

The exact source revision, episode, adapter commit, fixtures, rules,
Metriplane commit, artifacts, hashes, and tested environments in
`proof-record.json` are part of every supported claim. The proposed tag is not
yet published, so the candidate must not yet be called a stable public proof.

## Supported by the public proof

After the focused proof PR is merged, its workflows pass, and the immutable
tag exists, the exact tagged record supports these bounded statements:

- One exact official ManiSkill Demonstrations `PickCube-v1` motion-planning
  episode, episode `0` / HDF5 group `traj_0`, was normalized through the
  recorded source-specific adapter into contract-valid, position-only
  Metriplane fixtures.
- Source selection was outcome-blind within an official corpus that had already
  been success-filtered upstream. This is a limitation, not a claim of unbiased
  sampling.
- All 74 source transitions and all 75 stored source states are accounted for,
  and all 75 stored states were retained as normalized frames. The registered
  50-step RL horizon remains separate provenance and does not truncate the
  fixture.
- Every stored state was restored through named APIs. The adapter selected the
  cube pose and Panda TCP pose, copied source-world X/Y, emitted normalized Z
  as `0.0`, and used a deterministic `0.05 s` state-index clock.
- Normalization used no action integration, rendering, interpolation,
  resampling, carry-forward, fabricated confidence, or source annotation as
  Atlas incident truth.
- Source Z and all orientation were excluded. The proof is position-only and
  cannot evaluate 3D placement or attitude.
- Incident and control use byte-identical normalized state, with shared
  `session.jsonl` SHA-256
  `7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`,
  and the same entity mapping and operator-configured target geometry.
- The target polygon, inclusive-boundary rule, overlap rejection, outside
  label, and both waits are Layer-C operator rules. They are not source task
  truth or a ManiSkill success definition.
- Under those rules, changing only the relative wait from `0.20 s` to `0.30 s`
  changes the recorded bounded result: the incident is `75/4/1/1`
  frames/events/deviations/incidents, while the control is `75/3/0/0`.
- The incident evaluation produces one evidence bundle that passes the public
  bundle verifier and one generated regression that passes the documented
  public regression command.
- The no-incident control produces no evidence bundle and no generated
  regression. No placeholder or fabricated control artifact is presented.
- Three clean source conversions produced the recorded equivalent fixture
  bytes and fingerprints under the pinned conversion environment.
- The checked-in portable fixtures can be validated and evaluated without
  ManiSkill, SAPIEN, Torch, h5py, Vulkan, the adapter environment, raw source
  files, or simulator assets.
- Clean installed-wheel environments listed as passing in
  `artifacts/environment-matrix.json` produced the recorded Level-A results.
  This is an environment-specific owner/CI result, not an independent-user
  claim.
- The included representative artifacts are covered by `SHA256SUMS`, were
  built from the candidate commit identified in `proof-record.json`, and passed
  the recorded local-path and raw-source scans. This claim is usable after a
  final rebuild confirms that candidate commit is the frozen publication head.
- The fixture uses identified upstream source data; raw source bytes and assets
  are referenced, not included. The normalized fixture is treated as
  modified/derived data under its recorded Apache-2.0 attribution and notice,
  separately from MIT-licensed Metriplane software, adapter code, and proof
  documentation.

These statements are technical and bounded. They do not turn the source
trajectory, operator rule, or simulator output into a physical-world claim.

## Supported only after future external action

The proof package alone does not support any statement below. Each requires a
separate, attributable outside action and a record of what was actually done:

- independent reproduction;
- third-party technical validation;
- independent external installation or successful run;
- uncompensated external use;
- outside source-to-fixture conversion;
- independent issue, discrepancy report, or critical review;
- third-party integration or reuse;
- external adoption or deployment;
- external citation;
- U.S. organizational evaluation or interest;
- industry use;
- ManiSkill maintainer review, approval, validation, or endorsement; or
- evidence that a result generalizes to another episode, task, simulator,
  robot, dataset, or physical workcell.

Compensated evaluation may be described only with its compensation disclosed.
A CI runner is not an independent user. PASS and FAIL are both external
technical evidence when reported accurately; neither may be converted into an
endorsement claim.

## Prohibited

Do not claim or imply any of the following from this proof:

- official ManiSkill PickCube success or failure;
- detection or prediction of the upstream source outcome;
- grasp failure, successful grasp, or grasp-state evaluation;
- robot-control failure or controller evaluation;
- 3D placement, source Z, or orientation evaluation;
- physical accuracy, measurement accuracy, calibration accuracy, or metrology;
- simulator realism or fidelity;
- sim-to-real validity or transfer;
- robot, machinery, product, or process safety;
- quality, safety, regulatory, or conformity certification;
- production readiness, industry readiness, or suitability for a live cell;
- a ManiSkill-authored target region, wait, process rule, or task-success
  definition;
- native ManiSkill integration;
- general ManiSkill compatibility beyond the exact pinned source, episode,
  adapter, normalization, and rules;
- compatibility with other ManiSkill versions, tasks, episodes, or assets;
- ManiSkill approval, validation, affiliation, sponsorship, or endorsement;
- an unbiased or representative sample of PickCube behavior;
- official validation by the source dataset authors;
- independent reproduction, external validation, independent adoption,
  external citation, third-party endorsement, U.S. organizational interest, or
  industry use before the corresponding outside evidence exists;
- that published PyPI or conda-forge `metriplane==0.3.0` contains the proof's
  `metriplane external` commands;
- that a locally built proof wheel is the published v0.3.0 package;
- that RRID:SCR_028813 identifies this proof rather than the Metriplane
  resource; or
- that this proof has a DOI.

No wording may hide the upstream success-filtered-corpus limitation, the
position-only information loss, the operator origin of the polygon and waits,
the owner-generated evidence classification, or the absence of independent
reproduction.
