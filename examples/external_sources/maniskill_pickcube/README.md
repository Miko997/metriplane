<!--
SPDX-FileCopyrightText: NOASSERTION
SPDX-License-Identifier: Apache-2.0
-->

# ManiSkill PickCube position-only fixtures

This directory contains two portable, source-derived compatibility fixtures made
from one pinned official ManiSkill `PickCube-v1` demonstration. Metriplane did
not create the source demonstration. The incident and control variants evaluate
the same 75 normalized planar snapshots and the same target geometry under two
different Metriplane-authored relative waiting rules.

These fixtures are deliberately narrower than the upstream task. They evaluate
bounded XY occupancy and timing only. They do not evaluate official PickCube
success or failure, 3D placement, orientation, grasp state, physical accuracy,
simulator realism, robot safety, or certified quality.

## License, attribution, and modification notice

The files in this fixture subtree are treated separately from Metriplane's MIT
software. They are distributed under the
[Apache License 2.0](../../../LICENSES/Apache-2.0.txt) through the repository's
REUSE metadata. This fixture-scoped treatment does not change the license of the
repository as a whole.

The source dataset card declares `apache-2.0`. No standalone dataset `LICENSE`
file was found at the pinned dataset revision. The fixture cites both the
[ManiSkill project](https://github.com/mani-skill/ManiSkill/tree/a4a4f9272ad64b1564035874b605ceb687b63ed8)
and the
[ManiSkill Demonstrations dataset](https://huggingface.co/datasets/haosulab/ManiSkill_Demonstrations/tree/d674485bbffdd533914e52d272fdda34c0515608).

Modification notice: the normalized coordinates in these fixtures are
modified/derived data. The adapter restores named source state through the
pinned ManiSkill runtime, selects the cube and Panda TCP, projects source world
X/Y without translation, rotation, scaling, or axis swapping, sets normalized Z
to `0.0`, assigns zones against an operator-authored polygon, and emits a fixed
state-index clock. The source demonstration data were not created by
Metriplane.

The raw source ZIP, HDF5, and JSON are referenced and are not included. Panda
robot files, table/environment assets, checkpoints, simulator packages, videos,
and screenshots are also absent. The conversion environment may access those
upstream materials under their own terms; the portable fixture does not
redistribute them.

## Exact frozen source identities

The source release, dataset revision, and dataset-generation identity are
separate facts:

| Identity | Frozen value |
| --- | --- |
| Source project | `mani-skill/ManiSkill` |
| Conversion release | `v3.0.1` |
| Conversion source commit | `a4a4f9272ad64b1564035874b605ceb687b63ed8` |
| Conversion package | `mani_skill==3.0.1` |
| Conversion wheel SHA-256 | `685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a` |
| Dataset repository | `haosulab/ManiSkill_Demonstrations` |
| Dataset revision | `d674485bbffdd533914e52d272fdda34c0515608` |
| Dataset-generation package | ManiSkill `3.0.0b4` |
| Dataset-generation commit | `652ad9353c0223507a938f0e8d990dd6f1c771ad` |
| Task | `PickCube-v1` |
| Episode / HDF5 group | `0` / `traj_0` |
| Transitions / stored states / normalized frames | `74` / `75` / `75` |
| Registered RL horizon | `50`, provenance only |
| Control frequency / period | `20 Hz` / `0.05 s` |

Every conversion must reject any source whose size or hash differs:

| Referenced source artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `demos/PickCube-v1.zip` | 36,590,010 | `b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8` |
| `demos/PickCube-v1/motionplanning/trajectory.h5` | 29,349,195 | `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a` |
| `demos/PickCube-v1/motionplanning/trajectory.json` | 228,218 | `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90` |

The frozen External Source Contract v1 JSON Schema SHA-256 is
`b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4`.
Each variant's `source-manifest.json` records its exact adapter commit,
conversion parameter references, and source identities. Its
`CHECKSUMS.sha256` is the authoritative fixture inventory. This README does not
predeclare a final adapter commit, shared session hash, or fixture fingerprint.

## Position-only normalization

Each of frames `0` through `74` is a complete snapshot with exactly two
authoritative objects:

| Normalized object | Atlas asset kind | Named source API |
| --- | --- | --- |
| `cube_1` | `material` | `cube.pose` |
| `robot_tcp_1` | `tool` | `agent.tcp_pose` from the restored Panda articulation |

The authoritative time is `ts_sim_ns(i) = i * 50_000_000`; descriptive seconds
are `ts(i) = i * 0.05`. There is no interpolation, resampling, carry-forward,
fabricated confidence, action integration, or normalized source event. The
simulator is never stepped to reconstruct state.

The source cube, TCP, and goal poses are three-dimensional and include
orientation. Normalization intentionally discards:

- source Z for the cube and TCP, while emitting normalized Z as `0.0`;
- each complete source quaternion, including the numerically well-defined audit
  yaw, plus roll and pitch;
- velocities, grasp/contact state, and the full robot articulation other than
  the named TCP position obtained through pinned forward kinematics;
- source reward, success/failure, termination, truncation, and task outcomes;
- the goal-site Z and orientation; and
- render, camera, image, and simulator-asset material.

No orientation is hidden in object `extra`, another normalized object, or an
auxiliary Atlas input. The source goal pose and projected goal XY are retained
only as inert provenance and operator rationale. The goal marker is not emitted
as a process object.

## One session, one geometry, two relative waits

The incident and control fixtures use the same 75-frame normalized session and
the same Layer-C target definition. Their authoritative `session.jsonl` files
are required to be byte-identical. Consult each variant's manifest and
`CHECKSUMS.sha256` for the generated hashes rather than copying a hash from this
README.

The target is an inclusive square in source-world XY, with no coordinate
transform:

- center: `(0.026815734803676605, -0.0019813179969787598)` metres;
- half-extent: `0.010000000` metres;
- vertices, in stable order:
  `(0.016815734803676603, -0.01198131799697876)`,
  `(0.03681573480367661, -0.01198131799697876)`,
  `(0.03681573480367661, 0.00801868200302124)`, and
  `(0.016815734803676603, 0.00801868200302124)`;
- zone / station: `target_xy_region` / `target_station`;
- boundary policy: inclusive;
- overlap policy: reject; and
- outside label: `outside_workspace`.

> The operator froze this planar target region after inspecting the selected source goal pose. The region is a Metriplane compatibility-test rule, not a ManiSkill task-success definition.

The polygon belongs wholly to the supplied domain pack. It is not dynamically
derived during conversion and is not an official ManiSkill success region.

The cube enters the declared region at frame `66`; the TCP enters at frame
`71`, producing a `0.25 s` missing-tool interval under the fixed clock. The
waits below are relative durations beginning when the cube is present and the
required TCP is missing. They are not absolute trajectory timestamps.

| Variant | Relative `max_wait_s` | Compatibility-test expectation |
| --- | ---: | --- |
| `incident` | `0.20` | Four Atlas events, one deviation, and one `missing_tool_caused_delay` incident before subsequent TCP presence and step completion |
| `control` | `0.30` | TCP presence and step completion before the wait limit; three Atlas events, no deviation, and no incident |

Under a Metriplane-authored planar process rule, the cube occupied the target XY
region while the required robot TCP had not yet entered that region. This is a
cube-plus-required-tool timing experiment, not PickCube failure detection. The
variant `expected-outcome.json` files are test metadata only and are never
supplied to Atlas.

## Source annotations and selection limitation

Reward, success, termination, truncation, elapsed steps, task/environment
labels, actions, and the registered RL horizon are inventoried for provenance
but do not affect normalized positions, identities, time, zones, process rules,
events, deviations, incidents, or expected results. A standalone source
`failure` array is absent.

Episode selection was outcome-blind within an official corpus that had already
been filtered upstream. The selected episode is not an unbiased sample of
PickCube behavior.

## Conversion environment

Conversion is source-specific and isolated under
`adapters/maniskill_pickcube/`. It requires the pinned adapter environment,
ManiSkill `3.0.1`, SAPIEN, Torch, h5py, and potentially a software Vulkan device
because upstream scene construction creates render-material objects. Conversion
does not render or create video or screenshots.

From the adapter directory, after installing its frozen environment:

```bash
uv sync --frozen

uv run maniskill-pickcube acquire \
  --out <source-dir> \
  --json

uv run maniskill-pickcube inspect \
  --trajectory <source-dir>/extracted/PickCube-v1/motionplanning/trajectory.h5 \
  --metadata <source-dir>/extracted/PickCube-v1/motionplanning/trajectory.json \
  --episode-id 0 \
  --json

uv run maniskill-pickcube convert \
  --trajectory <source-dir>/extracted/PickCube-v1/motionplanning/trajectory.h5 \
  --metadata <source-dir>/extracted/PickCube-v1/motionplanning/trajectory.json \
  --config config/frozen-config.json \
  --adapter-commit 95d1134d9fb9273318c552c507952f1c5c26877e \
  --out <generated-fixture-root> \
  --json
```

Use an empty generated output outside this checked-in directory. This preserves
the checked-in README while allowing the converter's atomic output checks to
remain fail-closed. The exact commit supplied to `--adapter-commit` identifies
the frozen implementation and is recorded in each generated manifest.

## Portable evaluation environment

After conversion, fixture validation and Atlas evaluation require only an
ordinary installed Metriplane wheel and its declared runtime dependencies.
ManiSkill, SAPIEN, Torch, h5py, Vulkan tooling, the adapter, and raw source files
are not required.

```bash
metriplane external validate <fixture-root>/incident --json

METRIPLANE_GIT_COMMIT=<exact-metriplane-head> \
  metriplane external run <fixture-root>/incident \
    --out <incident-run> \
    --run-id maniskill_pickcube_incident \
    --json

metriplane external validate <fixture-root>/control --json

METRIPLANE_GIT_COMMIT=<exact-metriplane-head> \
  metriplane external run <fixture-root>/control \
    --out <control-run> \
    --run-id maniskill_pickcube_control \
    --json
```

The incident run may generate a checksummed evidence bundle and regression from
the Atlas incident. A zero-incident control run must not fabricate either.

## Allowed claims

After validating the manifests and checksums, it is accurate to say that:

- the identified official source bytes were converted through a recorded,
  source-specific adapter into a contract-compliant position-only fixture;
- all 75 stored states were retained with a deterministic fixed-step clock;
- Atlas evaluated normalized cube and TCP positions under supplied planar
  target-region and relative-wait rules;
- the incident and control share normalized state and target geometry and differ
  in the declared process wait; and
- the finished portable fixtures can be validated and evaluated without the
  simulator or source assets.

These claims are bounded to the exact source revision, episode, adapter commit,
rules, Metriplane commit, and tested environments recorded by the fixture and
run artifacts.

## Prohibited claims

Do not claim or imply:

- official ManiSkill PickCube success, failure, or source outcome prediction;
- grasp failure, successful grasp, 3D placement, or orientation evaluation;
- physical accuracy, calibration, simulator realism, or sim-to-real validity;
- a ManiSkill-authored target region or task-success definition;
- robot safety, certified quality, machinery control, or production readiness;
- general or native ManiSkill compatibility beyond this exact pinned fixture;
- an unbiased sample of PickCube behavior;
- ManiSkill endorsement; or
- independent adoption, independent validation, or third-party deployment of
  Metriplane.

This is a repository-authored compatibility fixture. It is not evidence of
independent adoption.

For the complete field-level trust map and audit history, see the
[field-provenance record](../../../docs/specs/maniskill-pickcube-field-provenance.md),
[source-selection record](../../../docs/specs/maniskill-pickcube-source-selection.md),
and [rights matrix](../../../docs/specs/maniskill-pickcube-rights-matrix.md).
