<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can low-dimensional verification ledger

Status: **LOCAL REAL-SOURCE CONVERSION, CONTRACT VALIDATION, SOURCE-TREE
EXECUTION, AND LINUX INSTALLED-WHEEL GATES PASS. macOS jobs, PR workflows,
merge, and post-merge verification remain pending.**

This ledger records the reproducibility evidence for one bounded,
position-only fixture derived from the official robomimic Can Proficient Human
(`ph`) dataset. It does not establish official Can success or failure, 3D
placement, grasp state, orientation, physical accuracy, safety, general
robomimic compatibility, or source-project endorsement.

## Frozen identities

| Item | Frozen value |
| --- | --- |
| Adapter commit | `cfc285a3e757fdf742858b1c4cf685c384d01e8b` |
| Adapter version | `1.0.0` |
| Dataset repository / revision | `robomimic/robomimic_datasets` / `74fa018461f479cd9fd15b924a16103012096203` |
| Selected source record | Can `ph`, `data/demo_0`, all 118 rows |
| Raw artifact | `v1.5/can/ph/demo_v15.hdf5`, 64,932,974 bytes, SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d` |
| Prepared artifact | `v1.5/can/ph/low_dim_v15.hdf5`, 46,889,752 bytes, SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962` |
| Raw / prepared simulator metadata | robosuite `1.5.0` / `1.5.1` |
| Frozen configuration SHA-256 | `3cfa88b1512215d8545c1404bcc80e18bf780d1dfc899553ccc69c2517c623c5` |
| Adapter lock SHA-256 | `86dab2c05dce00cb40db03ddea9848da227451661cd30aaa0f3eda72a35fc4ff` |
| Shared session SHA-256 | `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246` |
| Entity mapping SHA-256 | `51735e2c4e416c951d5d355dbb271a89f467354a9cab41fef386fa105c671a8c` |
| Incident fixture fingerprint | `6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6` |
| Control fixture fingerprint | `dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf` |
| Contract / frame model | External Source Contract v1 schema SHA-256 `b5544012d7d98f1fdc8aed56192c33ac16f4acebd6694778ad682743482722c4`; FrameStateModel `1.0` |

The fixture fingerprints are the SHA-256 values of each finalized
`CHECKSUMS.sha256`; they are not source hashes. Raw HDF5, prepared HDF5,
embedded XML, simulator assets, images, video, and source-framework code are
referenced or excluded rather than included in the portable fixture.

## Real-source audit and three conversions

The adapter compared all 200 raw/prepared demos before selecting `demo_0`.
The durable per-bundle attestation and root conversion summary record:

- exact `num_samples`, `states`, `actions`, `model_file`, and eight mask
  membership arrays for 200/200 demos and 23,207 rows;
- 23,207 array-exact Can witnesses from the named raw `Can_joint0` qpos;
- 23,207 independently reconstructed TCP witnesses to the named
  `gripper0_right_grip_site`, with maximum absolute error
  `1.1102230246251565e-15` metres;
- 23,207 verified clock rows, including all 23,007 within-demo intervals;
- raw environment version `1.5.0` and prepared version `1.5.1` kept distinct;
- identical raw/prepared hashes before and after conversion; and
- `source_unchanged_during_conversion: true`, published only after the
  post-conversion hashes passed and the staged candidate was atomically moved
  into place.

Three conversions from those exact bytes were written to separate empty roots
with run IDs `real-source-clean-1`, `real-source-clean-2`, and
`real-source-clean-3`. The public finalizer replayed the frozen writer and
required byte identity for 28 variant artifacts (14 per variant), exact root
summary equality, the same source attestation, and byte-identical
incident/control sessions. It finalized with
`comparison_policy: sha256_byte_identity`, `equivalent: true`, and
`status: demonstrated`.

The normalized clock is exact integer arithmetic:

```text
ts_sim_ns(i) = i * 50_000_000, i = 0..117
ts(i) = ts_sim_ns(i) / 1_000_000_000
```

There is no action replay, `next_obs` consumption, interpolation, resampling,
carry-forward, wall-clock input, or horizon-derived timing. Every frame is a
complete snapshot containing exactly `can_1` and `robot_tcp_1`. Source world
X/Y are retained in metres; source Z and complete object/TCP orientation are
discarded, and normalized Z is `0.0`.

## Frozen geometry and observed state interval

The target is an inclusive Layer-C square centered at
`(0.123724912698951, -0.20150121318116285)` metres, with half-extent `0.02`
metres. It is wholly operator-authored and is not the source task's official
success definition.

| Entity | Inside rows | Entry / exit |
| --- | --- | --- |
| `can_1` material | `0..63` | Present at row 0; first outside row 64 (`3.20 s`) |
| `robot_tcp_1` tool | `42..64` | First inside row 42 (`2.10 s`); first outside row 65 (`3.25 s`) |

“Required asset missing” means that the normalized TCP is outside this
operator region. It does not mean that the TCP entity or its snapshot is
absent.

## Contract validation and three-run equivalence

Unchanged `metriplane external validate` passed both finalized variants: 118
frames, two complete entities per frame, no errors, the shared session hash
above, and agreement among manifest, mapping, session, report, checksums,
domain pack, and Metriplane `0.3.0` runtime declaration.

Three clean source-tree evaluations of each variant produced canonically
identical state, events, deviations, incidents, and generated regressions:

| Variant | Relative wait | Exact event order | Frames / events / deviations / incidents | Evidence |
| --- | ---: | --- | --- | --- |
| Incident | `2.0 s` | `required_asset_missing` at frame 0 / `0.0 s`; `step_delayed` at frame 40 / `2.0 s`; `required_asset_present`, then `step_completed`, at frame 42 / `2.10 s` | `118 / 4 / 1 / 1` | One `missing_tool_caused_delay` incident from `0.0` through `2.0 s`; `INC-0001.zip` verified; generated regression passed |
| Control | `2.5 s` | `required_asset_missing` at frame 0 / `0.0 s`; `required_asset_present`, then `step_completed`, at frame 42 / `2.10 s` | `118 / 3 / 0 / 0` | No evidence bundle and no generated regression, as required |

The incident ends at the `2.0 s` delay threshold rather than the later TCP
arrival. The existing evaluator writes `unknown_required_asset` as the
`asset_type` placeholder on missing/delay events; the required stable asset ID
remains `robot_tcp_1`, and present events resolve its configured type as
`tool`.

Atlas completes this single process step at frame 42 and does not reopen it.
The later Can and TCP exits are therefore inert. This is a bounded arrival and
required-presence timing check, not a retention or continuing co-occupancy
check.

## Installed-wheel portability

An ordinary `metriplane-0.3.0-py3-none-any.whl` was built outside the fixture
and installed into isolated environments outside the checkout. The installed
package list contained only Metriplane and its ordinary runtime dependencies.
It contained no adapter, fixture, HDF5/XML/model payload, robomimic, robosuite,
MuJoCo, Torch, h5py, or Hugging Face dependency. Package-consistency checks
passed in both environments.

| Local platform | Python | Incident runs | Control runs | Move/reverify | Path and ZIP scan |
| --- | --- | ---: | ---: | --- | --- |
| Linux x86_64 | `3.12.13` | 3 equivalent, `118/4/1/1` | 3 equivalent, `118/3/0/0` | Pass | Pass |
| Linux x86_64 | `3.13.14` | 3 equivalent, `118/4/1/1` | 3 equivalent, `118/3/0/0` | Pass | Pass |

Across both interpreters the incident canonical semantic SHA-256 was
`fdf02146435923f0aadce3cdbe1060bea92e52a55cb38243daac1a0ad266c374`;
the control was
`b103f07b729a16003aa90f54bc940c34eb8561068a497fe94cca98bfb9558780`.
Every incident run produced one verifiable bundle and one passing regression.
Every control produced neither. Reports, dashboards, and USDA replays remained
readable after both the input and output roots moved. Recursive scans of moved
fixtures, outputs, ZIP member names, and ZIP bodies found no checkout,
execution-root, user-home, or platform-private path.

The workflow repeats this matrix on Ubuntu and macOS for Python 3.12 and 3.13.
The two macOS rows are pending GitHub execution; they are not inferred from the
Linux result. Conversion remains a separate Linux-only activity and is not a
portable-runtime requirement.

## Adapter, anti-taint, and negative verification

The isolated adapter suite result at the recorded head is **36 passed**; Ruff
reported no findings for adapter source and tests. Source-shaped paired
mutations demonstrated that rewards, dones, actions and action-like metadata,
filter membership, horizon, `next_obs`, excluded object-vector slices,
quaternions, orientation, and episode-end metadata do not change normalized
frames when the two consumed prepared world-position streams and raw witnesses
are unchanged.

Negative coverage rejects wrong revisions and hashes, raw/prepared mismatch,
missing or malformed nodes, unknown shape/dtype/unit/frame/clock, nonfinite
values, HDF5 soft/external/virtual links and unsupported filters, action replay,
source/output overlap, symlinks, overwrite without permission, source mutation,
incomplete snapshots, local-path leakage, and incident/control state drift.
Malformed HDF5 node types at `data`, `mask`, demo, `states`, `actions`, `obs`,
`next_obs`, object/TCP datasets, and mask membership return actionable adapter
errors rather than uncaught exceptions.

The public finalizer additionally rejected all of the following with zero
accepted corruptions and zero uncaught exceptions:

- **5/5** self-consistent semantic attacks against wait/rule files, expected
  outcome, mapping, adapter environment, and dependency lock;
- **32/32** root-summary leaf/extra-key fuzz mutations; and
- **28/28** individual bundle-inventory byte-corruption attacks.

Invalid JSON, a non-object envelope, non-finite JSON, stale or self-consistently
rewritten checksums, extra files, nested symlinks, and incident/control session
mismatch were also rejected. Adapter identity is bound to the exact clean Git
`HEAD`: false all-zero and earlier valid commits, hidden assume-unchanged or
skip-worktree content/mode changes, untracked adapter files, replacement refs,
hostile Git/config/loader environment variables, and non-checkout conversion
were rejected.

## Root protection and local quality gates

- isolated adapter: **36 passed**; Ruff check and format clean;
- fixture-specific suite: **11 passed**;
- full repository suite with a writable sandbox home: **1,089 passed, 2
  skipped**;
- preserved ManiSkill proof/fixture plus generic external-contract examples:
  **39 passed**;
- bundled `metriplane demo`: incident, evidence, and regression pass;
- synthetic fixture: unchanged generic validation pass;
- fixture checksum inventories: both pass;
- scoped REUSE 5.0.2 validation for every new/modified MET-18 path: pass;
- root `pyproject.toml`, root `uv.lock`, `metriplane/`, FrameStateModel 1.0,
  External Source Contract v1, ManiSkill fixture/proof, and CALVIN audit: byte
  unchanged from `a8b67d58e00f7fcb9b090b2c95475d51b0ede81c` where applicable; and
- package version: unchanged at `0.3.0`; no release or tag was created.

A repository-wide REUSE invocation still reports pre-existing unlicensed-path
debt outside MET-18. The scoped new paths pass; this record does not relabel the
whole pre-existing tree REUSE-compliant.

## Gates still open

- GitHub Ubuntu/macOS jobs on Python 3.12/3.13, including fresh runner package
  installation;
- PR review and merge; and
- post-merge workflows and the final Linear completion record.

MET-18 must remain In Review rather than Done until those gates close.

## Exact MET-19 row and remaining instruction

Use this factual row after merge, without broadening it:

| Source | Decision | Exact boundary | Rights | Clock | Fields / loss | Result | Portability | Limitations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| robomimic | GO | Can PH `demo_0`; dataset `74fa018461f479cd9fd15b924a16103012096203`; raw SHA-256 `86961df85af1b9c6b9d4182a3755a8a4db6d0660cd550e45cca1f7accdb6d73d`; prepared SHA-256 `3f2eb92e0a5025d0095e866ac16cc8092d6a762abe27dec90dbaff9027282962`; adapter `cfc285a3e757fdf742858b1c4cf685c384d01e8b` | Dataset and modified numeric fixture MIT with attribution/notice | VERIFIED, artifact-native `50,000,000 ns` per retained row | Prepared world Can/TCP XY witnessed against raw state/model; Z and orientation discarded | Incident `118/4/1/1`; control `118/3/0/0`; shared session SHA-256 `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246` | Linux installed wheel 3.12/3.13 pass; macOS rows only after green CI | One upstream success-filtered trajectory; operator polygon/waits; arrival timing only; no source success, accuracy, safety, endorsement, or general compatibility |

Remaining instruction: review and merge the focused PR, require all post-merge
workflows to pass, then mark MET-18 Done and copy the row above into MET-19.
Do not start MET-19 automatically.

Episode selection was outcome-blind only within an upstream success-filtered corpus.
