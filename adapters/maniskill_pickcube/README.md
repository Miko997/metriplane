<!-- SPDX-FileCopyrightText: 2026 Miko Parkkinen -->
<!-- SPDX-License-Identifier: MIT -->

# ManiSkill PickCube adapter

This is an isolated, source-specific converter for exactly one locked ManiSkill
Demonstrations artifact and episode. It is not part of the Metriplane runtime package. Its
portable output needs neither ManiSkill, SAPIEN, Torch, h5py nor Vulkan.

The converter uses ManiSkill 3.0.1 at commit
`a4a4f9272ad64b1564035874b605ceb687b63ed8`. The dataset was generated separately with
ManiSkill 3.0.0b4 at commit `652ad9353c0223507a938f0e8d990dd6f1c771ad`, from dataset
revision `d674485bbffdd533914e52d272fdda34c0515608`. Those are separate identities.

## Locked source

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `demos/PickCube-v1.zip` | 36,590,010 | `b2d4afb30fa309755862b98c342e6ee18918253c93f3bbac16ed6670748f26d8` |
| `trajectory.h5` | 29,349,195 | `03ca60546541a7f18321d9d32721f0254bc75217828c0cadacd217d0c014576a` |
| `trajectory.json` | 228,218 | `16e403cb77bfbdda28c243b96eb90adbae1c0edf42854283be57ee47076a2e90` |

Only episode `0` / HDF5 group `traj_0` is accepted: 74 transitions and 75 stored states.
Every stored state is retained. The registered 50-step RL horizon is provenance only.
Wrong bytes, shapes, dtypes, metadata, runtime version, timing, or named-state restoration
fail closed.

## Commands

Create the isolated environment from the checked lock:

```console
UV_CACHE_DIR=/tmp/maniskill-pickcube-uv uv sync --no-config --project adapters/maniskill_pickcube --frozen
```

Acquire the immutable ZIP revision, safely extract it, and verify all three hashes:

```console
maniskill-pickcube acquire --out SOURCE_DIR --json
```

A previously downloaded archive can be verified without another download:

```console
maniskill-pickcube acquire --archive PickCube-v1.zip --out SOURCE_DIR --json
```

Inspect structure and independently restore every state through the named APIs:

```console
maniskill-pickcube inspect \
  --trajectory SOURCE_DIR/extracted/demos/PickCube-v1/motionplanning/trajectory.h5 \
  --metadata SOURCE_DIR/extracted/demos/PickCube-v1/motionplanning/trajectory.json \
  --episode-id 0 --json
```

Convert using the exact commit that contains the frozen adapter implementation:

```console
maniskill-pickcube convert \
  --trajectory trajectory.h5 \
  --metadata trajectory.json \
  --config adapters/maniskill_pickcube/config/frozen-config.json \
  --adapter-commit FULL_40_HEX_FREEZE_COMMIT \
  --out fixture-root --json
```

The upstream scene construction may require a software Vulkan device even though conversion
never renders. That is only a Linux conversion-environment dependency. The converter constructs
the exact `PickCube-v1` CPU environment, confirms 20 Hz / 0.05 s, calls
`env.unwrapped.set_state_dict(state)` independently for each stored state, and reads
`cube.pose`, `agent.tcp_pose`, and `goal_site.pose`. It never steps the environment or integrates
actions.

The adapter does not mark three-conversion equivalence from one invocation. Its generated
normalization report remains `not_demonstrated` until the review workflow performs three named,
clean conversions in separate output roots and records their byte-identical results. A fixture
must not be published with a `demonstrated` claim before that external evidence exists.

After three independent `convert` invocations using the same locked source, config, and adapter
commit, finalize them without manual JSON edits:

```console
maniskill-pickcube finalize-equivalence \
  --conversion-root clean-1 --run-id real-source-clean-1 \
  --conversion-root clean-2 --run-id real-source-clean-2 \
  --conversion-root clean-3 --run-id real-source-clean-3 \
  --out finalized-fixture-root --json
```

The finalizer requires exact file inventories, compares every file in both variants byte-for-byte,
and only then rewrites the normalization reports, manifest hashes, checksum inventories, and
conversion summary to record `demonstrated` with those three stable run IDs.

## Frozen normalization and rule boundary

The authoritative session contains exactly `cube_1` (material) and `robot_tcp_1` (tool) in
all 75 complete frames. World X/Y are copied, normalized Z is zero, and integer time is
`ts_sim_ns(i) = i * 50_000_000`; `ts` is derived from that integer clock. No interpolation,
resampling, carry-forward, confidence, source outcomes, or normalized events are used.

The complete source quaternion exists and audit yaw was numerically well-defined. Source Z,
quaternion, yaw, roll, and pitch are deliberately discarded. This position-only fixture evaluates
bounded XY occupancy and timing. It does not evaluate 3D placement, orientation, grasp state,
official PickCube success/failure, physical accuracy, or simulator realism.

The target square is read from the frozen configuration, never derived at conversion time. Its
exact center is `(0.026815734803676605, -0.0019813179969787598)` metres, half-extent is `0.01`
metre, and boundaries are inclusive. The whole polygon and station association are Layer-C
operator rules. The operator froze this planar target region after inspecting the selected source
goal pose. The region is a Metriplane compatibility-test rule, not a ManiSkill task-success
definition.

Both outputs have byte-identical session, mapping, geometry, assets, source identities, source
annotations, and adapter identity. Only the declared fixture/domain identities, process wait,
expected metadata, and hashes caused by those differences vary:

| Variant | Relative `max_wait_s` | Expected Atlas counts |
| --- | ---: | --- |
| incident | 0.20 s | 4 events, 1 deviation, 1 `missing_tool_caused_delay` incident |
| control | 0.30 s | 3 events, 0 deviations, 0 incidents |

Under that Metriplane-authored planar process rule, the cube occupied the target XY region while
the required robot TCP had not yet entered that region. This is not PickCube failure detection,
grasp-failure detection, source-success prediction, or an official task evaluation.

## Annotation and rights boundary

Reward, success, terminated, truncated, actions, elapsed steps, task labels, and horizon metadata
are inventoried but cannot feed normalized fields or Atlas semantics. The official corpus was
recorded through a success-only upstream process: episode selection was outcome-blind within an
official corpus that had already been filtered upstream.

The ZIP, HDF5, JSON, Panda/table assets, screenshots, and video are not redistributed. Adapter
source is independently authored MIT software. Portable normalized coordinates are modified or
derived data treated separately under Apache-2.0 attribution and notice, as recorded in each
contract manifest. This does not make the whole repository Apache-2.0 and does not claim that
Metriplane created the source dataset.

## Tests

```console
PYTHONPATH=adapters/maniskill_pickcube/src \
  pytest -q adapters/maniskill_pickcube/tests
```

The fast suite covers pure conversion, exact clocks, inclusive boundaries, negative cases,
archive traversal/symlink rejection, and quaternion/outcome/action/horizon anti-taint. A review
must additionally run the real-source conversion and validate both portable fixtures through the
Metriplane External Source Contract and Atlas evaluator.
