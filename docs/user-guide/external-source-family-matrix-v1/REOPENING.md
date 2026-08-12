<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Reopening-criteria register

Reopening changes only a named, bounded row after new evidence is reviewed. It
does not widen an existing decision by analogy. All new work requires its own
authorization, immutable source identity, rights review, and External Source
Contract v1 evaluation.

| Source family | Current decision | Reopening criteria |
| --- | --- | --- |
| ManiSkill | **GO** | The exact tagged PickCube proof needs no reopening. Any broader source, task, episode, field, clock, transform, conversion environment, platform, or semantic claim requires a new bounded audit and fixture. Independent-rerun status changes only after an attributable outside evaluator completes the evaluator packet; owner CI is not independent validation |
| CALVIN | **NO-GO** | All four gates must close: (1) official dataset terms or explicit permission for the debug archive and public redistribution of derived state; (2) immutable archive/revision identity and authoritative correction-status record; (3) source-authoritative per-sample timestamps or an official exact fixed-step guarantee satisfying External Source Contract v1 without invention; and (4) independent full-archive verification followed by outcome-blind validation of every candidate sample. Maintainer contact requires separate owner authorization |
| robomimic | **GO** | The exact Can Proficient Human `demo_0` path needs no reopening. A different task, dataset version, prepared-field set, episode, semantic rule, source environment, or claim requires a new bounded audit and fixture. Independent status requires an attributable outside rerun. Any exact frozen-byte conversion rerun must preserve adapter provenance `cfc285a3e757fdf742858b1c4cf685c384d01e8b`, not substitute current checkout HEAD |
| MimicGen | **PARTIALLY SUPPORTED** | Approve a narrower source boundary or obtain an official immutable original-raw and preparation record for the selected human source; establish artifact-specific authoritative clock evidence; then perform deterministic local preparation and complete rights, field, frame, unit, identity, completeness, and information-loss audits before a new decision. There is currently no adapter or fixture |
| RoboCasa / RoboCasa365 | **NOT TESTED** | Open a separately authorized source audit with one exact artifact and immutable revision. Verify source-specific rights, clock, frames, units, identity, completeness, provenance, information loss, and deterministic conversion before any implementation or support decision. Do not populate cells from another HDF5 family |
| ROS 2 / MCAP + TF2 | **NOT TESTED** | Begin [MET-46](https://linear.app/metriplane/issue/MET-46/extract-a-minimal-metriplane-source-adapter-sdk-and-prove-a-ros-2mcap) only after separate owner authorization. Select one legally usable immutable recording and pin its schemas, topics, entities, TF path, units, authoritative clock/domain, snapshot/materialization policy, rights, and hashes. Implement a deterministic isolated conversion and ROS-independent portable fixture before changing this row. No ROS 2 or MCAP claim exists today |

## Decision interpretation

- A **GO** is fixed to the exact source-specific artifact, mapping, fixture, and
  evaluation evidence named by that row.
- A **NO-GO** proves the gate stopped publication; it does not count as
  compatibility.
- **PARTIALLY SUPPORTED** for MimicGen means partially audited and not
  implemented. It is neither a GO nor a completed rejection.
- **NOT TESTED** leaves unknown cells unknown. It is not evidence for or against
  eventual compatibility.

An optional immutable publication tag or archive may be considered only after
owner review of this candidate. This register does not authorize a tag, archive,
release, DOI, new adapter, or any of the future work described above.
