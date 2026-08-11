<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube verification ledger

Status: **CURRENT EVIDENCE RECORDED — final-head distribution, matrix, CI, PR,
and repository-wide REUSE gates remain open.**

This ledger records the verification evidence currently available for the
bounded, position-only ManiSkill PickCube compatibility fixture. It separates
completed source conversion and current source-tree Atlas checks from gates
that can be run truthfully only after the branch head is final and a wheel has
been built from that exact head.

Nothing in this record changes the claim boundary. The fixture evaluates
bounded XY occupancy and timing under a Metriplane-authored process rule. It
does not evaluate official PickCube success or failure, 3D placement,
orientation, grasp state, physical accuracy, simulator realism, robot safety,
or certified quality.

## Evidence identities

| Item | Recorded identity |
| --- | --- |
| Original Metriplane base | `5475c6a66b0535cddcbcc7bb05032aed1d2017db` |
| Preserved audit commit | `cfba11932ee1deb51491d9c60f5afe434b8ee054` |
| Adapter freeze commit | `8a0c878be9670423d1610c5d89fb090bcd1d5735` |
| Fixture commit | `dcbc46c91c796f7a8e0bdfc7d76d6e063a485d87` |
| Adapter configuration SHA-256 | `2062eb44090276b7933e15600d286f532c15f3399746dbe15738bb0411d5e202` |
| Conversion input fingerprint | `fe90ca129c924d183cecdacc05c5fa0f8a5711dd169cb034128f0da33a2c4475` |
| Named restored-pose stream SHA-256 | `1c2fe261f0bb2190683900e5b751c9416a18f13b6a6485c45969809bd48860d2` |
| Shared session SHA-256 | `7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df` |
| Entity mapping SHA-256 | `9127535a2e8eb3091aeac82f335e001f81c3a9e5098272881f7969c6eeecbee7` |
| Incident fixture fingerprint | `b45b71495d50686bcffa3f4e230d0b8325ef1fd0ffdfc2775e53c1f041ad8a04` |
| Control fixture fingerprint | `cb5c157aec19381affcceb025b375caa6bef1b6179df58ce6faa290312881f68` |

The fixture fingerprints are the SHA-256 values of the finalized variant
`CHECKSUMS.sha256` files. They are not source hashes. The conversion input
fingerprint is the External Source Contract v1 Stage-1 fingerprint recomputed
from each strict manifest; both variants produce the same value.

The locked upstream source identities remained:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `demos/PickCube-v1.zip` | 36,590,010 | `b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8` |
| `demos/PickCube-v1/motionplanning/trajectory.h5` | 29,349,195 | `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a` |
| `demos/PickCube-v1/motionplanning/trajectory.json` | 228,218 | `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90` |

The conversion runtime was ManiSkill `3.0.1` at commit
`a4a4f9272ad64b1564035874b605ceb687b63ed8`, using the wheel with SHA-256
`685de2f03c300b1ede49881a1bf6306ad062082d39c8d3be8b8e85603f32e33a`.
The dataset-generation identity remained separately recorded as ManiSkill
`3.0.0b4` at commit
`652ad9353c0223507a938f0e8d990dd6f1c771ad`.

## Three clean conversions

Three conversions were executed into distinct empty roots from the same
verified HDF5 and JSON, frozen configuration, dependency lock, and adapter
freeze commit. The operational absolute temporary roots are deliberately not
provenance and are not persisted. The exact invocation shape and fixed
arguments were:

```console
for index in 1 2 3; do
  maniskill-pickcube convert \
    --trajectory "$SOURCE_ROOT/extracted/PickCube-v1/motionplanning/trajectory.h5" \
    --metadata "$SOURCE_ROOT/extracted/PickCube-v1/motionplanning/trajectory.json" \
    --config adapters/maniskill_pickcube/config/frozen-config.json \
    --adapter-commit 8a0c878be9670423d1610c5d89fb090bcd1d5735 \
    --out "$THREE_CONVERSION_ROOT/conversion-$index" \
    --json
done

maniskill-pickcube finalize-equivalence \
  --conversion-root "$THREE_CONVERSION_ROOT/conversion-1" \
  --run-id real-source-clean-1 \
  --conversion-root "$THREE_CONVERSION_ROOT/conversion-2" \
  --run-id real-source-clean-2 \
  --conversion-root "$THREE_CONVERSION_ROOT/conversion-3" \
  --run-id real-source-clean-3 \
  --out "$THREE_CONVERSION_ROOT/final" \
  --json
```

The finalizer result was:

```json
{
  "compared_artifact_count": 28,
  "control_fixture_fingerprint_sha256": "cb5c157aec19381affcceb025b375caa6bef1b6179df58ce6faa290312881f68",
  "equivalent": true,
  "incident_fixture_fingerprint_sha256": "b45b71495d50686bcffa3f4e230d0b8325ef1fd0ffdfc2775e53c1f041ad8a04",
  "run_ids": [
    "real-source-clean-1",
    "real-source-clean-2",
    "real-source-clean-3"
  ],
  "schema_version": "org.metriplane.maniskill_pickcube.equivalence.v1"
}
```

The count comprises the same fourteen-file inventory for each variant. All 28
variant artifacts were byte-identical across the three clean roots, and the
three root `conversion-summary.json` files were separately byte-identical.
The finalizer then changed only the equivalence declarations and their caused
manifest/checksum hashes. The finalized normalization reports record
`comparison_policy: sha256_byte_identity`, `equivalent: true`, and
`status: demonstrated` for the three stable run IDs.

All three conversions retained 75 states, placed cube entry at frame `66` and
TCP entry at frame `71`, and reported the same `0.25 s` missing-tool interval.
The source HDF5 and JSON hashes remained the locked values after conversion.

## Contract and fixture validation

The finalized checked-in fixtures were validated independently:

```console
python -m metriplane.cli external validate \
  examples/external_sources/maniskill_pickcube/incident --json

python -m metriplane.cli external validate \
  examples/external_sources/maniskill_pickcube/control --json
```

Both returned `pass: true`, 75 frames, no validation errors, and matching
External Source Contract v1, FrameStateModel 1.0, domain-pack, mapping,
normalization-report, checksum, and runtime-version checks. The frozen contract
schema SHA-256 remained
`b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4`.

The two fixture trees have the same fourteen-path inventory. The session,
entity mapping, assets, workspace, work orders, adapter environment, frozen
configuration, and dependency lock are byte-identical. Structured differences
are limited to:

- fixture and domain-pack identifiers and title;
- `max_wait_s = 0.20` versus `0.30` in `process.yaml` and
  `contracts.yaml`;
- test-only expected outcomes;
- the normalization-report fixture identifier; and
- directly caused manifest and checksum values.

No raw ZIP, HDF5, JSON, Panda/table asset, checkpoint, video, screenshot, or
source package is included. All source artifacts are immutable references. The
fixture rights declaration is `derived_only`, with fixture-scoped Apache-2.0
attribution and a modified-data notice distinct from the repository's MIT
software licensing.

## Adapter and anti-taint suite

The isolated adapter suite was run with the root test runner and the pinned
conversion environment on `PYTHONPATH`:

```console
PYTHONPATH=adapters/maniskill_pickcube/src:$CONVERSION_ENV/site-packages \
  .venv/bin/pytest -q adapters/maniskill_pickcube/tests
```

Result: **31 passed**.

Those tests include source-shaped mutations of reward, success, failure,
terminated, truncated, action values, registered horizon, and complete source
quaternions. They demonstrate byte-identical normalized sessions and shared
domain-pack/mapping outputs when positions and the frozen operator rules are
unchanged. They also cover source hash and structure failures, timing and named
pose failures, archive traversal and symlink rejection, input/output overlap,
source mutation detection, exact configuration freeze enforcement, and
expected CLI failures without tracebacks.

`CONVERSION_ENV` denotes the isolated CPython 3.12 environment represented by
the fixture's pinned `source/uv.lock`; it is not an ordinary Metriplane runtime
dependency. This fast source-shaped suite does not replace the real-source
conversions recorded above.

## Current Atlas executions and path portability

The current fixture/path suite was run as:

```console
pytest -q tests/external_sources/test_maniskill_pickcube_fixture.py
```

Result: **13 passed**.

The suite executed three incident and three control Atlas evaluations and
compared canonical semantics. Each current incident execution produced:

- 75 frames;
- `required_asset_missing` at frame `66`;
- `step_delayed` at frame `70`;
- `required_asset_present` and `step_completed` at frame `71`;
- four events, one deviation, and one
  `missing_tool_caused_delay` incident;
- one verified evidence bundle; and
- one passing generated regression.

Each current control execution produced:

- 75 frames;
- `required_asset_missing` at frame `66`;
- `required_asset_present` and `step_completed` at frame `71`;
- three events, zero deviations, and zero incidents; and
- no evidence bundle or generated regression.

The same suite copied and moved run directories, removed the original fixture
execution path, and rechecked contained state/config references, reports,
dashboard, USDA, incident evidence, and regression behavior. Recursive text and
ZIP-member scans found none of the path sentinels, operational temporary roots,
Unix home paths, Windows drive-prefixed paths, repository roots, source cache
paths, raw source payloads, or false camera/tracking/calibration assumptions.

These are current source-tree executions. They establish the expected semantics
and path behavior but are **preliminary with respect to the final branch head
and installed-wheel matrix**.

## Gates still open

The following results must not be inferred from the evidence above:

- the final branch head has not yet been frozen in this ledger;
- a Metriplane wheel and sdist have not yet been built from that exact final
  head and subjected here to `twine check --strict` and archive inspection;
- the clean installed-wheel Python 3.12/3.13 portability matrix remains
  pending, including moved-run evaluation without ManiSkill, SAPIEN, Torch,
  h5py, Vulkan tools, or the adapter;
- the final-head full focused/relevant test, Ruff, mypy, strict MkDocs, demo,
  root CLI, and frozen-evidence checks remain pending;
- GitHub CI remains pending;
- no PR is claimed open by this ledger;
- the final Linear evidence handoff and move to In Review remain pending; and
- repository-wide `reuse lint` is not green. The scoped adapter/fixture REUSE
  metadata is present, but the pre-existing global repository inventory remains
  a separate unresolved gate and no blanket license correction is claimed.

The preliminary three-run result must be repeated from the exact final-head
wheel before PR readiness is claimed. A failure in any open gate restores
PAUSE; it must not be hidden by changing the source, episode, polygon,
thresholds, orientation boundary, or expected outcomes.

## Claim boundary

The current evidence supports only these bounded statements:

- the exact frozen source was converted through the recorded isolated adapter
  into two contract-valid position-only fixtures;
- all 75 stored states were retained under the fixed integer clock;
- the incident and control use byte-identical normalized state and the same
  Layer-C geometry, differing in the declared relative wait;
- three clean source conversions were byte-equivalent under the recorded
  conversion environment; and
- current source-tree Atlas and path-portability checks produced the recorded
  bounded planar results.

It does not support official PickCube success/failure, 3D or orientation
evaluation, physical or simulator accuracy, safety certification, general
ManiSkill compatibility, independent adoption, or final PR/CI readiness.
