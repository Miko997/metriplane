<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# robomimic Can low-dimensional fixture red-team gate

Status: **LOCAL ADVERSARIAL, REAL-SOURCE, CONTRACT, SOURCE-TREE, AND LINUX
INSTALLED-WHEEL GATES PASS. macOS CI, PR review, merge, and post-merge
verification remain open and block a Done claim.**

This record adversarially reviews the exact fixture identified by adapter
commit `cfc285a3e757fdf742858b1c4cf685c384d01e8b`, shared session SHA-256
`bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246`,
incident fingerprint
`6ea89f1d4a4ceb8605a8670db3f2065b09f8043b665ef5815d8799f2c5c3b0e6`,
and control fingerprint
`dc9d9f24a04f663e84489869eac3a648894d013674f6d62a889892cea592bddf`.

## Required questions

| # | Question | Evidence-based disposition |
| ---: | --- | --- |
| 1 | Can a reader mistake the result for official source-task success? | **Pass.** Manifests, reports, expected outcomes, and documentation call it operator-authored planar occupancy/timing and explicitly deny Can success/failure, grasp, and 3D placement claims. |
| 2 | Can prepared observations be mistaken for raw data? | **Pass.** `object[:,7:10]` and `robot0_eef_pos` remain named prepared fields. Raw states/XML are correspondence witnesses, not emitted source values. |
| 3 | Can operator geometry be mistaken for source truth? | **Pass.** The inclusive row-0-centered square and both waits are Layer-C Metriplane rules, not robomimic or robosuite semantics. |
| 4 | Does reward, done, success, failure, or filter membership affect conversion? | **Pass.** They are excluded; paired anti-taint mutations leave normalized frames unchanged. Filter arrays are read only for exact raw/prepared correspondence. |
| 5 | Does any action affect conversion? | **Pass.** Actions are an equality witness only. No action is stepped or integrated; action mutations leave normalized state unchanged. |
| 6 | Is the source clock evidenced? | **Pass.** Both artifacts embed 20 Hz; 23,007 within-demo raw simulation-time deltas are `0.05 s` within floating error, prepared states are exact copies, and rows map to `i * 50,000,000 ns`. |
| 7 | Is rollout horizon separated from timing? | **Pass.** Horizon is excluded evaluation metadata and affects neither row retention, timestamps, wait, nor process rules. |
| 8 | Is every consumed HDF5 component named and proven? | **Pass.** Can world position is `data/demo_0/obs/object[:,7:10]`, witnessed by named `Can_joint0` qpos; TCP is `robot0_eef_pos`, witnessed by embedded-XML FK to named `gripper0_right_grip_site`. |
| 9 | Are world and relative frames distinguished? | **Pass.** Only proven robosuite-world positions are used. The relative Can-to-EEF block is inventoried and excluded. |
| 10 | Are Z and orientation losses explicit? | **Pass.** Both source Z values and complete quaternions, yaw, roll, and pitch are declared losses; normalized Z is `0.0`; no orientation is hidden in `extra`. |
| 11 | Are raw and prepared artifacts independently identified? | **Pass.** Immutable revision, exact paths, sizes, and distinct SHA-256 values are recorded; raw robosuite `1.5.0` and prepared `1.5.1` remain distinct. |
| 12 | Does portable fixture evaluation require source dependencies? | **Pass on Linux 3.12/3.13.** Six runs per interpreter family used only the ordinary installed wheel and runtime dependencies; no adapter or source framework was installed. macOS CI remains pending. |
| 13 | Does the ordinary wheel contain source material or adapter dependencies? | **Pass.** Wheel archive, metadata, and installed distributions contain no adapter, source fixture, raw data/model payload, or prohibited source dependency; package version remains `0.3.0`. |
| 14 | Can local paths be found in durable artifacts? | **Pass locally.** Recursive scans of fixture, moved output, ZIP member names, and ZIP bodies found no checkout, original execution-root, home, or platform-private path. CI independently repeats this. |
| 15 | Are incident/control sessions identical? | **Pass.** Both hash to `bc97300ef173f2c60635197d9e54bef0447752a483d3bd747ca2f449a5455246`. |
| 16 | Are variant differences limited to declared rules? | **Pass.** State, mapping, geometry, assets, work order, frozen config, environment, and lock are identical. Differences are fixture/domain identities, `max_wait_s` (`2.0`/`2.5`), expected-outcome metadata, and directly caused hashes. |
| 17 | Are rights for normalized state explicit? | **Pass for the frozen boundary.** The immutable dataset card declares MIT; raw/prepared HDF5 and embedded XML are excluded; the modified normalized fixture retains attribution and a modification notice. |
| 18 | Can exact source drift be detected? | **Pass.** Immutable revision, sizes, and source hashes are mandatory before inspection and are recomputed after conversion; publication is atomic only after post-hash equality. |
| 19 | Are three conversions deterministic? | **Pass.** Three empty-root conversions were byte-equivalent across 28 variant artifacts plus exact root summaries and finalized as demonstrated. |
| 20 | Are three runs semantically equivalent? | **Pass in source-tree and installed-wheel Linux 3.12/3.13 tests.** Incident repeated `118/4/1/1`; control repeated `118/3/0/0`; canonical state/events/deviations/incidents/regressions matched within and across interpreters. |
| 21 | Is upstream corpus filtering visible? | **Pass.** The required limitation appears in durable manifests and documentation: “Episode selection was outcome-blind only within an upstream success-filtered corpus.” |
| 22 | Is independent adoption or endorsement implied? | **Pass.** Both claims are prohibited; this is one internally verified trajectory and no source endorsement is asserted. |
| 23 | Did the CALVIN rejection weaken a gate? | **Pass.** Rights, clock, raw/prepared, deterministic conversion, and claim gates were applied independently and remain stricter than public-download inference. |
| 24 | Is the result suitable as a factual MET-19 row? | **Yes as a factual local GO row.** It must retain one-trajectory, operator-rule, position-only, upstream-filtering, no-success/no-accuracy limitations and keep macOS/merge fields pending until closed. |

## Outcome-specific adversarial findings

The incident produces, in order, `required_asset_missing` at frame 0,
`step_delayed` at frame 40, then `required_asset_present` and
`step_completed` at frame 42. Its exact result is 118 frames, four events, one
`missing_required_asset` deviation, one `missing_tool_caused_delay` incident,
one verified evidence bundle, and one passing generated regression. The
incident ends at the `2.0 s` threshold, not at the `2.10 s` arrival.

The control produces `required_asset_missing` at frame 0, then
`required_asset_present` and `step_completed` at frame 42: 118 frames, three
events, no deviation, no incident, no evidence bundle, and no regression.
Expected-outcome files are test metadata with `atlas_input: false`.

Two semantic caveats are mandatory:

1. Atlas marks the one process step complete at frame 42 and does not reopen
   it. The Can leaves at frame 64 and the TCP at frame 65, but those later exits
   are inert. This fixture tests arrival/required-presence timing, not continued
   retention or co-occupancy.
2. Missing/delay events use the evaluator's existing
   `unknown_required_asset` `asset_type` placeholder. This is not source truth
   and does not change the stable required asset ID `robot_tcp_1`; subsequent
   present/completed events resolve the configured role as `tool`.

## Falsification record

| Attack family | Attempts | Accepted / uncaught | Result |
| --- | ---: | ---: | --- |
| Self-consistent durable bundle semantics: wait/rules, expected outcome, mapping, adapter environment, dependency lock | 5 | `0 / 0` | Frozen-writer replay rejected every mutation. |
| Root conversion-summary leaf changes and extra keys | 32 | `0 / 0` | Exact canonical object equality rejected every envelope mutation. |
| Individual byte corruption across 14 files in each variant | 28 | `0 / 0` | Inventory, checksum, attestation, and writer replay rejected every corruption. |

Further malformed-input probes produced actionable errors rather than
tracebacks: invalid JSON, list envelopes, non-finite JSON, stale checksums,
self-consistent schema corruption, incident/control session divergence, and
wrong HDF5 node types at `data`, `mask`, demo, `states`, `actions`, `obs`,
`next_obs`, named position datasets, and mask members.

Path attacks against source, config, conversion root, output, parent output,
and nested bundle paths were rejected when any path component was a symlink.
HDF5 soft/external links, virtual datasets, unsupported filters, extra root or
variant files, and source/output overlap were rejected. A destination-symlink
attack left the external victim marker unchanged.

A forced raw-source mutation after staging but before publication caused a
post-conversion hash failure. The adapter removed the temporary candidate,
preserved the pre-existing output marker, and published no fixture. Thus the
durable `source_unchanged_during_conversion` attestation is conditioned on a
successful post-hash and atomic publish.

Adapter identity attacks were also rejected: false all-zero and valid earlier
commits, hidden assume-unchanged or skip-worktree content and executable-mode
changes, untracked adapter files, hostile `GIT_DIR`/`GIT_WORK_TREE`/index/object
and loader/config variables, fake `PATH`, replacement refs, and installed
non-checkout conversion. Conversion requires the exact clean committed adapter
tree; portable fixture evaluation does not require Git or the adapter.

## Decision and remaining blockers

No local red-team finding requires retuning the selected demo, polygon, waits,
field map, clock, or contract. The exact local result is supported, subject to
the one-shot and placeholder disclosures above.

The dedicated adapter, fixture, root, preserved-proof, demo, distribution, and
Linux installed-wheel gates are green. The local wheel archive and installed
distributions exclude source material and adapter dependencies; Python 3.12 and
3.13 each repeated validation, three incident/control runs,
evidence/regression policy, relocation, and path/ZIP scans. GitHub must still
repeat the portable rows on Ubuntu and macOS. PR review, merge, and post-merge
workflows remain separate pending gates.

If any pending gate changes the frozen semantics or reveals a source
dependency, path leak, rights defect, nondeterminism, or misleading public
claim, stop rather than weaken the boundary or tune the fixture.
