<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube verification ledger

Status: **CORRECTION CANDIDATE — the 2026-08-12 public-provenance correction
passed all required local gates, including exact-head installed-wheel Python
3.12/3.13. PR review/CI, merge, and post-merge verification remain open.**

This ledger records the verification evidence currently available for the
bounded, position-only ManiSkill PickCube compatibility fixture. It separates
completed source conversion, current source-tree Atlas checks, and preliminary
candidate-distribution checks from gates that can be closed truthfully only
after the branch head is final and a wheel has been built from that exact head.

Nothing in this record changes the claim boundary. The fixture evaluates
bounded XY occupancy and timing under a Metriplane-authored process rule. It
does not evaluate official PickCube success or failure, 3D placement,
orientation, grasp state, physical accuracy, simulator realism, robot safety,
or certified quality.

## Evidence identities

| Item | Recorded identity |
| --- | --- |
| Original Metriplane base | `5475c6a66b0535cddcbcc7bb05032aed1d2017db` |
| Preserved audit commit | `683d725f7ab92dd3915cf98efdf48b605ad551ec` |
| Adapter freeze commit | `95d1134d9fb9273318c552c507952f1c5c26877e` |
| Original public fixture commit | `d311d2d6c2ecd76b1dfec1102a76786f172be22d` |
| Adapter configuration SHA-256 | `2062eb44090276b7933e15600d286f532c15f3399746dbe15738bb0411d5e202` |
| Conversion input fingerprint | `9eb29e2c52b5ab3e59801b12b19b14385fe5b176a90f71a08df566d1f03d6eb1` |
| Named restored-pose stream SHA-256 | `1c2fe261f0bb2190683900e5b751c9416a18f13b6a6485c45969809bd48860d2` |
| Shared session SHA-256 | `7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df` |
| Entity mapping SHA-256 | `9127535a2e8eb3091aeac82f335e001f81c3a9e5098272881f7969c6eeecbee7` |
| Incident fixture fingerprint | `954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2` |
| Control fixture fingerprint | `8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e` |

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
    --adapter-commit 95d1134d9fb9273318c552c507952f1c5c26877e \
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
  "control_fixture_fingerprint_sha256": "8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e",
  "equivalent": true,
  "incident_fixture_fingerprint_sha256": "954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2",
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

## Earlier preliminary root-suite and distribution checks

The full root suite was executed against a candidate branch state using a
writable temporary-home shim required by the sandboxed test environment:

```console
pytest -q
```

Result: **1,057 passed, 2 skipped**.

The same candidate state also passed the root package build, strict Twine
distribution check, and strict MkDocs build:

```console
python -m build
python -m twine check --strict dist/*
python -m mkdocs build --strict
```

Both the wheel and sdist passed the strict Twine check, and the documentation
site completed under strict mode. These results are preliminary candidate
evidence. The tested branch state was not declared the exact final head, so
this ledger does not relabel those artifacts as final-head distributions or
use them to close the final distribution gate.

## Earlier preliminary Python 3.12 installed-wheel portability

A clean CPython 3.12 environment outside the repository installed the candidate
Metriplane wheel and its ordinary declared runtime dependencies from an offline
package set. ManiSkill, SAPIEN, Torch, h5py, Vulkan tools, and the isolated
adapter were not installed. Both checked-in fixtures validated and executed
through the installed `metriplane` command.

The installed-wheel incident result matched the current source-tree semantics:
75 frames, four events in the recorded order, one deviation, one
`missing_tool_caused_delay` incident, a verified evidence bundle, and a passing
generated regression. The control result likewise matched: 75 frames, three
events, zero deviations, zero incidents, and no fabricated evidence bundle or
regression.

Each run directory was then moved away from its original execution location.
After the original fixture execution paths were removed where safe, the
run-contained session and configuration references, report, dashboard, USDA,
and applicable incident bundle/regression behavior remained usable. The
recursive durable-artifact scanner reported:

```text
PATH_LEAK_FAILURES 0
```

This preserves one clean, offline CPython 3.12 pre-correction candidate-wheel
result. It is not an exact-final-head wheel claim, does not cover CPython 3.13,
and must be repeated from the final frozen head before PR readiness is
asserted.

## Public-provenance correction verification — 2026-08-12

The earlier record used local-lineage Metriplane commit identities. Git history
preserves that superseded record; the current fixture and this ledger use only
the publicly reachable equivalents. The public adapter freeze is
`95d1134d9fb9273318c552c507952f1c5c26877e`. It resolves publicly and has the
same complete repository tree
`f9532701629d924e55c6d4f82da71b00e3cffa63` and adapter subtree
`54ec32baadc11ce7de6e8d419a1369aa36f4671e` as the superseded local-lineage
commit. The preserved public audit and original fixture commits are
`683d725f7ab92dd3915cf98efdf48b605ad551ec` and
`d311d2d6c2ecd76b1dfec1102a76786f172be22d`.

The exact pinned PickCube source was reacquired and verified. Inspection passed
under CPython 3.12.13, the pinned adapter lock, ManiSkill 3.0.1, and software
Vulkan, recording 74 transitions, 75 stored states, and the provenance-only
50-step RL horizon. Three fresh conversions using the public adapter commit
were written to separate empty roots and finalized. The finalizer compared 28
variant artifacts, returned `equivalent: true`, and produced:

- conversion input fingerprint:
  `9eb29e2c52b5ab3e59801b12b19b14385fe5b176a90f71a08df566d1f03d6eb1`;
- incident fixture fingerprint:
  `954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2`;
- control fixture fingerprint:
  `8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e`.

The finalized conversion trees were byte-identical to the corrected checked-in
fixtures. The source HDF5 and JSON hashes remained unchanged. The source,
episode, normalized session, entity mapping, geometry, relative waits, and
incident/control semantics were not changed.

| Correction-candidate gate | Result |
| --- | --- |
| Fixture checksum inventories | PASS |
| Isolated adapter and anti-taint suite | 31 passed |
| PickCube fixture/path suite | 13 passed |
| Full external-source suite | 119 passed |
| Full root suite | 1,057 passed, 2 skipped |
| Strict MkDocs build | PASS |
| Wheel/sdist build and strict Twine check | PASS |
| Distribution-content inspection | PASS; no adapter package, raw source, or prohibited simulator/ML assets |
| Focused Ruff | PASS |
| Global Ruff baseline delta | Zero delta; 1,083 diagnostics on both base and candidate |
| Global mypy baseline delta | Zero delta; the same duplicate-`conftest.py` exit 2 on base and candidate |
| Changed-path REUSE | PASS for all 15 changed paths |
| Global REUSE baseline delta | Zero delta; the same pre-existing repository inventory remains non-green |
| Exact-head installed wheel | PASS on CPython 3.12.13 and 3.13.14 |

The global Ruff, mypy, and REUSE commands are not represented as green. Their
correction gate is the recorded zero-delta disposition; every changed path
passes the scoped REUSE check.

The wheel built from the frozen correction head was installed into clean
CPython 3.12.13 and 3.13.14 environments outside the checkout. ManiSkill,
SAPIEN, Torch, h5py, Hugging Face tooling, Vulkan tooling, and the isolated
adapter were absent. On each interpreter, both fixtures validated and three
incident plus three control executions produced the frozen `75/4/1/1` and
`75/3/0/0` counts and event order. Incident bundles and generated regressions
verified; control executions produced neither. After the fixture and output
roots were moved away from their original paths, all six runs per interpreter
remained usable and recursive plain/ZIP scans reported
`PATH_LEAK_FAILURES 0`.

## Gates still open

- PR checks, review, and merge remain pending;
- post-merge workflows and public merged-tree verification remain pending; and
- the final Linear completion handoff remains pending.

The completed local results must not be relabeled as PR-CI or post-merge
evidence. Any discrepancy in a remaining gate restores PAUSE and must not be
hidden by changing the source, episode, polygon, waits, orientation boundary,
or expected outcomes.

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
  bounded planar results; and
- one preliminary candidate state passed the full root suite, distribution and
  strict documentation checks, plus one clean offline Python 3.12
  installed-wheel portability run with `PATH_LEAK_FAILURES 0`; and
- the frozen correction head passed clean installed-wheel validation,
  execution, evidence/regression, moved-run, and path-leak checks on CPython
  3.12.13 and 3.13.14.

It does not support official PickCube success/failure, 3D or orientation
evaluation, physical or simulator accuracy, safety certification, general
ManiSkill compatibility, independent adoption, cross-platform portability
beyond the recorded Linux CPython checks, or final-head PR/CI readiness.
