# ManiSkill PickCube source-selection record

Status: **technical selection frozen; final fixture selection remains contingent
on the architecture preflight.**

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
