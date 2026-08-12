<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# ManiSkill PickCube source-selection record

Status: **selection and implementation frozen; episode `0` remains selected and
all 75 states are present in the demonstrated fixtures.**

Historical preflight status, preserved as decision history: **technical
selection frozen; final fixture selection remains contingent on the
architecture preflight.**

## Predeclared selection rule

Select the lowest numeric episode ID satisfying all of these checks, without
reading reward, success, failure, termination, truncation, or other outcome
values:

1. matching JSON episode and HDF5 `traj_<episode_id>` group exist;
2. JSON `elapsed_steps` equals action count `T`;
3. actions have the expected finite numeric two-dimensional shape;
4. required named cube, goal-site, and Panda state arrays exist;
5. every required stored-state stream has length `T+1`;
6. all required numeric state values are finite;
7. stored actor/state dtypes and shapes are compatible with the pinned public
   state-restoration API;
8. source control timing can be resolved from pinned source/runtime
   configuration;
9. cube start and goal XY positions are distinguishable and the cube has
   non-degenerate XY motion; and
10. named state restoration succeeds without action integration or magic
    flattened-vector offsets.

The rule and exact source revision were timestamped in the project issue before
outcome values were inspected. The official corpus itself was generated with a
success-only recording option; therefore this record claims only outcome-blind
selection *within an already outcome-filtered official corpus*.

## Source inventory inspected

- Dataset repository: `haosulab/ManiSkill_Demonstrations`.
- Dataset revision: `d674485bbffdd533914e52d272fdda34c0515608`.
- HDF5 SHA-256:
  `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a`.
- JSON SHA-256:
  `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90`.
- JSON episode IDs and HDF5 groups both enumerate all integers from 0 through
  999 with no gap or mismatch.

All 1,000 episodes passed checks 1 through 6. Transition counts range from 49 to
103. Outcome arrays were checked only for the existence and length needed to
prove exclusion and T/T+1 accounting; their values were not used as criteria.

## Selected record

| Field | Value |
| --- | --- |
| Episode ID | `0` |
| HDF5 group | `traj_0` |
| JSON `elapsed_steps` | `74` |
| Source transitions/actions | `74` |
| Stored environment states | `75` |
| Proposed normalized frames | `75` |
| Registered RL horizon | `50` (separate metadata only) |
| Actions | shape `(74, 8)`, dtype `float32` |
| Cube actor states | shape `(75, 13)`, dtype `float32` |
| Goal-site actor states | shape `(75, 13)`, dtype `float32` |
| Table actor states | shape `(75, 13)`, dtype `float32` |
| Panda articulation states | shape `(75, 31)`, dtype `float32` |
| Reward array | length `74`; excluded |
| Success array | length `74`; excluded |
| Termination array | length `74`; excluded |
| Truncation array | length `74`; excluded |

## Geometry and restoration gate

Named restoration through ManiSkill v3.0.1 produced these descriptive values:

- cube first XYZ: `[-0.000748679, 0.053644367, 0.020000000]` m;
- cube last XYZ: `[0.020278862, -0.000906261, 0.286202340]` m;
- goal XYZ: `[0.026815735, -0.001981318, 0.288933456]` m;
- cube start-to-goal XY distance: approximately `0.0620807` m;
- cube end-to-goal XY distance: approximately `0.00662469` m;
- cube XY displacement: approximately `0.0584631` m;
- maximum named cube/goal pose difference from stored pose: `0.0`;
- minimum projected cube X-axis norm for yaw extraction: `0.9999962449`.

Three independent complete restorations returned the same pose-stream SHA-256:

```text
1c2fe261f0bb2190683900e5b751c9416a18f13b6a6485c45969809bd48860d2
```

The complete 75-state trajectory is retained in any future conversion. The
50-step horizon must not truncate it, set an Atlas deadline, or produce an event.

## Rejection record

No lower episode exists. No episode was rejected before episode 0 was selected.
Episodes 1 through 999 were inspected only to establish the corpus-wide
structural facts above; they were not ranked, compared by outcome, or considered
as alternatives after episode 0 passed the declared checks.

Final freeze remains paused for the cross-contract questions documented in
[`maniskill-pickcube-adapter-audit.md`](maniskill-pickcube-adapter-audit.md).

The preceding sentence is the original preflight disposition. The owner later
resolved those cross-contract questions without changing the selection rule,
source revision, task, episode, or state accounting.

## Implemented selection freeze — 2026-08-12

Episode `0` / `traj_0` remains the selected record. No later episode was
substituted, no outcome value was added to the selection criteria, and the
50-step registered RL horizon remained provenance only. The frozen adapter at
commit `95d1134d9fb9273318c552c507952f1c5c26877e` retained all 74 transitions
and all 75 stored states under configuration SHA-256
`2062eb44090276b7933e15600d286f532c15f3399746dbe15738bb0411d5e202`.

The incident and control variants contain byte-identical `session.jsonl` files
with SHA-256
`7302878b71b145df634fca84db321804b02764312584db43af6ad9e945f452df`.
Their canonical fixture fingerprints are:

- incident:
  `954a0ebbe3b541e12fedd91665484ff9561f0ae19fe63f83227379afe44413c2`;
- control:
  `8b3d26285f208bec42f8cb54401cda8d04c2c1e23fbeabb186eed6bd4c9dce1e`.

The two fixtures use the same operator-authored inclusive square centered at
`(0.026815734803676605, -0.0019813179969787598)` metres, with half-extent
`0.010000000` metres and vertices, in stable order:

1. `(0.016815734803676603, -0.01198131799697876)`;
2. `(0.03681573480367661, -0.01198131799697876)`;
3. `(0.03681573480367661, 0.00801868200302124)`; and
4. `(0.016815734803676603, 0.00801868200302124)`.

This geometry was frozen after selection and was not a selection criterion or
an official ManiSkill success region. The incident and control relative waits
are `0.20` seconds and `0.30` seconds respectively; they are Layer-C process
rules, not source outcomes or trajectory timestamps.

Three clean conversions from the same locked source, adapter, and configuration
were finalized as `real-source-clean-1`, `real-source-clean-2`, and
`real-source-clean-3`. Both normalization reports record
`comparison_policy: sha256_byte_identity`, `equivalent: true`, and
`status: demonstrated`. This establishes final conversion equivalence while
leaving the original outcome-blind selection claim unchanged. It does not by
itself claim Atlas three-run equivalence, installed-wheel portability, CI
completion, PR creation, or merge readiness.

The fixture subtree has separate Apache-2.0 modified/derived-data treatment;
the independently authored adapter remains MIT. Raw source bytes and assets are
still absent. This rights treatment does not affect selection and does not
convert the already success-filtered upstream corpus into an unbiased sample.
