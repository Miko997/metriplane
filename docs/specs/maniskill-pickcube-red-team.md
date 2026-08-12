<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube fixture red-team gate

Status: **READY FOR REVIEW — real-source, fixture, exact-head distribution,
Python matrix, quality baseline-delta, scoped rights, and PR workflow gates
pass. Review, merge, and post-merge verification remain open.**

This record is the adversarial pre-PR gate for the bounded ManiSkill PickCube
fixture. Current commands, hashes, counts, and evidence boundaries are recorded
in [`maniskill-pickcube-verification.md`](maniskill-pickcube-verification.md).
The evidence there covers three clean real-source conversions, current
source-tree Atlas/path checks, the exact-head installed-package matrix, and the
recorded zero-delta dispositions for pre-existing global quality and rights
debt. Correction PR #50 is ready for review. Merge and post-merge verification
remain separate gates.

The source remains frozen to episode `0` / group `traj_0` from dataset revision
`d674485bbffdd533914e52d272fdda34c0515608`. The conversion runtime remains
ManiSkill `3.0.1` at commit
`a4a4f9272ad64b1564035874b605ceb687b63ed8`; the dataset-generation identity is
separately recorded as ManiSkill `3.0.0b4` at commit
`652ad9353c0223507a938f0e8d990dd6f1c771ad`.

## Questions and evidence state

### 1. Can a reader mistake target-region entry for PickCube success?

**CURRENT EVIDENCE PASS.** The checked-in manifests, normalization reports,
README, current Atlas reports/dashboard, incident evidence and regression use
bounded XY occupancy and timing language under a Metriplane-authored process
rule. They explicitly deny official PickCube success/failure, 3D placement,
orientation, and grasp evaluation. The domain-pack rationale says the region is
not a ManiSkill task-success definition. The same bounded claims were retained
in the exact-head installed-wheel outputs.

### 2. Can a reader mistake the goal-centered polygon for source truth?

**CURRENT EVIDENCE PASS.** The entire polygon, including
its center, half-extent, vertices, boundary policy, and station association, is
Layer C operator-configured material in the hashed domain pack. The source goal
pose and projected XY value are inert source/adapter facts only. Required
rationale:

> The operator froze this planar target region after inspecting the selected
> source goal pose. The region is a Metriplane compatibility-test rule, not a
> ManiSkill task-success definition.

The checked-in manifest, field map, normalization report, and byte-identical
workspace files classify it as an operator-authored Layer-C rule. The source
goal pose and projected XY appear only as inert provenance and rationale; Atlas
runtime input receives the separately frozen domain-pack coordinates.

### 3. Does any source outcome field affect conversion?

**CURRENT EVIDENCE PASS.** Reward, success,
failure, termination, and truncation are excluded from normalized state, zone
assignment, process rules, and expected results. `FrameStateModel.events` must
remain empty. The 31-passing adapter suite includes source-shaped mutation and
optional-array removal checks and compares byte-identical `session.jsonl`,
entity mapping, and domain-pack outputs. The real source's absent standalone
failure array is explicitly inventoried as absent.

### 4. Does action data affect restored-state conversion?

**CURRENT EVIDENCE PASS.** Conversion restores each stored environment state
independently through `env.unwrapped.set_state_dict` and reads named
`cube.pose` and `agent.tcp_pose` APIs. It must never step the environment or
integrate actions.
The source-shaped action-mutation test produced byte-identical normalized state
and domain-pack files. The three real-source conversions also recorded
`actions_integrated: false` and the same named restored-pose stream hash.

### 5. Does the 50-step horizon affect the fixture?

**CURRENT EVIDENCE PASS.** The registered horizon is
provenance only. All 74 transitions and 75 stored states must be retained. It
must not truncate conversion, set `max_wait_s`, create an event, or affect zone
geometry. The metadata-mutation test changed the horizon without changing the
session, mapping, or process rules; all 75 states remain present.

### 6. Is orientation hidden anywhere?

**CURRENT EVIDENCE PASS.** The fixture is position-only. Source
quaternion, yaw, roll, and pitch are declared losses. Orientation must not appear
in `ObjectStateModel.extra`, another normalized field, a side stream consumed by
Atlas, zone assignment, process configuration, or event logic. Descriptive audit
values occur only in the inert namespaced manifest extension and audit
documentation. Recursive scans of both 75-frame sessions and supplied Atlas
inputs found no orientation, quaternion, yaw, roll, pitch, object `extra`,
confidence, fused stream, or auxiliary orientation input. Quaternion mutations
left normalized session bytes unchanged.

### 7. Does the fixture imply 3D placement?

**CURRENT EVIDENCE PASS.** Normalized Z is always `0.0`; source
Z is explicitly discarded. The observed source Z excursion is a prominent
limitation. Allowed descriptions are target XY-region occupancy, planar transit,
and planar arrival. The checked-in artifacts and current generated outputs were
reviewed and make no 3D placement, grasp, physical-accuracy, or sim-to-real
claim. The exact-head installed-wheel outputs retained the same limitations.

### 8. Is TCP genuinely represented as a tool?

**CURRENT EVIDENCE PASS.** The one-to-one mapping maps the restored Panda TCP
to normalized object and Atlas asset
`robot_tcp_1`. `assets.yaml` must classify it as `tool`, and the single process
step must list `robot_tcp_1` as its required asset. The cube must be the
`material` candidate. Strict fixture validation and current runs show agreement
across entity mapping, asset registry, process file, contract file, event
sequence, and incident. The required TCP becomes present at frame `71`.

### 9. Is `max_wait_s` treated as a relative duration?

**CURRENT EVIDENCE PASS.** The missing interval begins when
the cube first occupies `target_xy_region` while the required TCP does not. The
incident threshold is `0.20` seconds and the control threshold is `0.30`
seconds. Neither value is an absolute trajectory timestamp. The authoritative
clock must be `ts_sim_ns(i) = i * 50_000_000`; Atlas should therefore emit the
incident delay at frame 70 after the missing event at frame 66, before TCP entry
at frame 71. Three current incident executions emitted the delay at frame `70`
with threshold `0.20`; three control executions completed at frame `71` before
the `0.30` threshold. Neither threshold is treated as an absolute timestamp.

### 10. Are incident/control sessions byte-identical?

**PASS.** The incident and control sessions are byte-identical across all three
clean conversions and in the checked-in fixtures. Their shared SHA-256 is
`7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`.

### 11. Are the only substantive process differences declared?

**PASS.** The same source, episode, adapter, entity mapping, session, target
polygon, assets, and workspace were used. The substantive process difference
is only `max_wait_s`: `0.20` for the
incident variant and `0.30` for the control variant, mirrored in the process and
contract files. Fixture/domain-pack identity and test-only expected-outcome
metadata differ as declared. The recursive structured diff found no hidden
state, geometry, asset, mapping, annotation, adapter, or rule difference.
Exactly 14 paths exist in each variant; eight are byte-identical and the six
differing files contain only the allowed changes and caused hashes.

### 12. Can a run be moved without its original source path?

**PASS.** Atlas commit
`89f2877372471d9d449b355b93ef2fe4e8d8617d` makes new manifests refer to
run-contained `state_segment.jsonl` and
`configs`, introduces source-neutral safe resolution, and makes the USDA exporter
prefer those copies. The 13-passing fixture/path suite moved current incident
and control runs, removed their original fixture execution paths, and rechecked
the report, dashboard, USDA, incident evidence bundle, and regression from the
moved directories. The exact-head wheel repeated the check outside the
repository on CPython 3.12.13 and 3.13.14 for three incident and three control
runs per interpreter.

### 13. Does any durable artifact leak a local path?

**PASS.** New durable manifest references are run-relative.
The complete current incident and control output trees, including ZIP members,
were scanned for fixture, pack, output, home, repository, and cache sentinels,
Unix home paths, Windows drive-prefixed paths, and operational absolute roots.
The exact-head installed-wheel matrix repeated the recursive plain/ZIP scan
after moving all six runs per interpreter and reported `PATH_LEAK_FAILURES 0`.

### 14. Does any generated output assume camera, tracking, or calibration?

**PASS.** Atlas commit
`070421a2626f0fe0b9e197b28b2bc852410da569` replaces generic camera/tracking
assumptions with normalized-state
language and upstream-accuracy limitations. Camera-specific subsystem
documentation remains outside this change. Current reports, dashboard,
limitations, connectors, evidence metadata, regression, privacy report, and
USDA were searched and contain no false `camera`, `tracked`, `tagged`,
`calibrated`, `sensor`, `video`, `Isaac`, or source-latency assumption. The
exact-head installed-wheel outputs retained the same source-neutral claims and
were byte-identical across the recorded Python 3.12/3.13 runs.

### 15. Does the wheel contain source dependencies or assets?

**PASS.** The adapter is
isolated under `adapters/maniskill_pickcube/` with its own dependency lock. The
root package must not import or depend on ManiSkill, SAPIEN, Torch, h5py,
Hugging Face clients, or Vulkan bindings. The final wheel and sdist must be
inspected to prove that they contain no raw source, Panda/table assets, adapter
runtime, or source-framework dependency. The exact-head wheel and sdist contain
187 and 318 paths respectively; archive inspection found none of those source
dependencies or assets. Both clean wheel environments confirmed that the
adapter and source-framework packages were absent.

### 16. Are raw source artifacts absent?

**PASS.** The ZIP, HDF5,
JSON, Panda URDF, table asset, videos, screenshots, and checkpoints must remain
outside Git fixtures and Metriplane distributions. The portable fixture may
contain only normalized/derived material and immutable referenced source
identities. The checked-in fixture inventory and recursive file-type scan found
none of the prohibited raw artifacts or assets, and final wheel/sdist archive
inspection confirmed their absence.

### 17. Is fixture licensing distinct from repository software licensing?

**SCOPED PASS; GLOBAL ZERO-DELTA DISPOSITION.** Independently authored
adapter code remains MIT-licensed. Public source-derived fixture data is treated
separately under Apache-2.0 attribution and a modified-data notice. Raw source
bytes are referenced rather than redistributed. The final fixture manifest,
notices, Apache-2.0 license text, and REUSE metadata must agree and must not imply
that the entire repository is Apache-2.0 or that the demonstration data was
created by Metriplane. The manifests, notices, canonical license texts, and
narrow `.reuse/dep5` entries agree. All 15 changed paths pass `reuse lint-file`.
Repository-wide `reuse lint` remains non-green with exactly the pre-existing
baseline inventory and invalid-expression debt; the correction has zero global
delta and claims no blanket relicensing.

### 18. Can exact source drift be detected?

**CURRENT EVIDENCE PASS.** The
dataset revision, ZIP/HDF5/JSON paths, byte sizes, and SHA-256 values are frozen.
Acquisition must use the immutable dataset revision rather than `resolve/main`,
verify the archive before extraction, and verify both selected members before
inspection. Wrong-byte negative tests pass. All three real conversions started
from the exact locked HDF5/JSON hashes and reported those same hashes after
conversion; named restoration also matched the frozen pose-stream fingerprint.

### 19. Are three conversions deterministic?

**PASS.** Three conversions from the locked source were written to separate
empty roots and finalized only after byte comparison of all 28 variant
artifacts plus the root conversion summary. The final reports name
`real-source-clean-1`, `real-source-clean-2`, and `real-source-clean-3`, with
`status: demonstrated` and `equivalent: true`. The shared session SHA-256 is
`7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`;
the incident and control fixture fingerprints are respectively
`954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2`
and
`8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e`.

### 20. Are three Atlas executions semantically equivalent?

**PASS.** Three current incident and three current control evaluations produced
equivalent canonical semantics.
Each incident run produced four events, one deviation, one
`missing_tool_caused_delay` incident, a verified bundle, and a passing
regression. Each control run produced three events, zero deviations, zero
incidents, and no bundle or regression. The exact-head installed wheel repeated
all six runs with fixed safe run IDs on CPython 3.12.13 and 3.13.14, retaining
the incident `75/4/1/1` and control `75/3/0/0` results.

## Claims supported by current evidence

- The identified official source bytes were converted through the recorded
  source-specific adapter into a contract-compliant, position-only planar
  fixture.
- All 75 stored states were retained with a deterministic fixed-step clock.
- Atlas evaluated the normalized cube and TCP state under the supplied
  Metriplane-authored target-region and relative-wait rules.
- Three clean conversions were byte-equivalent under the recorded conversion
  environment, and source-tree plus exact-head installed-wheel incident/control
  executions were semantically equivalent.
- The portable fixture can be validated and evaluated without ManiSkill or its
  assets after conversion on the recorded CPython 3.12/3.13 Linux matrix.

These claims remain bounded to the exact source, episode, adapter, rules,
fixture commit, and tested environments. Do not describe PR evidence as merged
or post-merge evidence.

## Prohibited claims

Do not claim or imply:

- ManiSkill PickCube success or failure;
- 3D placement, grasp, or orientation evaluation;
- physical accuracy, simulator realism, or sim-to-real validity;
- robot safety, certified quality, or production readiness;
- general or native ManiSkill compatibility;
- ManiSkill endorsement;
- an unbiased sample of PickCube behavior;
- independent adoption or third-party validation of Metriplane.

The source corpus was success-filtered upstream. Episode selection was
outcome-blind only within that already filtered official corpus.

## Stop gate

Do not merge correction PR #50 until every current-head PR workflow is green.
Do not return MET-15 to Done or start MET-16 until the correction is merged and
every triggered `main` workflow plus the public merged-tree verification is
green. Stop rather than retune the frozen polygon, thresholds, source, episode,
or trust-layer assignments if a final result differs. A source hash mismatch,
nondeterministic restoration/conversion, source-tainted state or rules,
remaining durable path leak, misleading generated claim, unrepresentable
rights boundary, source dependency in the portable evaluator, or change to the
frozen contract or FrameStateModel is a blocking result, not a reason to weaken
the gate.
