<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Completeness and materialization decision

## Complete-snapshot rule

The source is a set of partial topic streams. The adapter emits a normalized
frame only after proving that all declared process-relevant dynamic state exists
at one exact source timestamp.

| Policy | Value |
| --- | --- |
| Sampling trigger | `/metriplane/material_pose` |
| Required dynamic topics | Material pose and tool pose |
| Required entities | `material_1`, `tool_1` |
| Synchronization tolerance | 0 ns |
| Dynamic-state lookup | Exact source timestamp only |
| Static state | One predeclared `/tf_static` message |
| Carry-forward | None |
| Interpolation | None |
| Resampling | None |
| Nearest selection | None |
| Extrapolation | None |
| Missing state | Reject the recording |
| Unknown state | Reject the recording |
| Duplicate trigger or observation | Reject the recording |

All 60 accepted timestamps contain exactly one valid observation for each
required entity. The adapter does not emit physical absence when observation is
missing.

## Zone materialization

After TF composition and planar projection, a separately authored inclusive
polygon assigns either `target_xy_region` or `outside_workspace`. Zone assignment
is an adapter-derived operation bound to the frozen polygon and boundary policy.
It is not a source field and is not inferred by Atlas from position.

## Operator timing variants

The incident and control variants use the same normalized session and polygon.
Only the Metriplane-authored maximum wait differs:

| Variant | `max_wait_s` |
| --- | --- |
| Incident | 0.5 |
| Control | 1.2 |

These values are frozen test rules, not source timing annotations. Final Atlas
outcomes are recorded only after the portable fixtures and evaluations reach
their immutable freeze point.

