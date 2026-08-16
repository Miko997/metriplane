<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Evaluation acceptance criteria

The evaluation is accepted only when the source can be handled transparently and
the result can be reproduced without turning unknown state into invented truth.

## Outcome model

### SUPPORTED

All required gates pass. The bounded source is converted with explicit
provenance, the portable fixture validates, the Metriplane run is deterministic,
and the nominated reviewer can inspect the mapping and result.

`SUPPORTED` applies only to the exact source, revision, selection, adapter,
parameters, process rule, and Metriplane version recorded in the evaluation.

### PARTIALLY SUPPORTED

The evaluation produces technically useful output, but one or more limitations
prevent full acceptance. Examples include incomplete source semantics, a
withheld artifact that limits independent reproduction, a bounded projection
loss, or a reviewer who can inspect but not rerun the result.

The limitation must be named. `PARTIALLY SUPPORTED` is not silently reported as
`SUPPORTED`.

### NOT SUPPORTED

A defensible evaluation cannot be completed under the current source and terms.
Common reasons include unclear rights, missing identity semantics, unknown versus
absent state that cannot be separated, unavailable transform information,
unsupported partial updates, or a requirement for live control or safety use.

`NOT SUPPORTED` is a valid result. It does not require a retry or a softened
public explanation.

## Gate A: source rights and scope

Required:

- The source and selection are identified.
- Data-use rights are confirmed for the agreed work.
- Redistribution status is explicit for every source artifact.
- Confidentiality, retention, and deletion terms are known.
- The evaluation question is narrow enough to answer from recorded state.
- No production connection is required.

Hard stop:

- Rights are unclear or disputed.
- The requested work requires confidential data before handling terms exist.
- The request depends on robot control, safety approval, or production authority.

## Gate B: source semantics

Required:

- Authoritative clock, timestamp field, and unit are known.
- Coordinate frame, units, axes, and transforms are known.
- Process-relevant entity identities are stable and mappable.
- Complete snapshots or a bounded materialization policy can be established.
- Unknown, unavailable, stale, and physically absent state are distinguishable.
- Projection, interpolation, synchronization, resampling, and carry-forward are
  explicit, including when not used.

Hard stop:

- Unknown state would have to be treated as absence.
- Entity identity cannot be made stable.
- Required coordinate or time semantics are missing.
- Hidden source labels would have to be used as incident truth.

## Gate C: adapter and provenance

Required:

- The adapter has a stable identifier, version, source revision, and environment.
- Every normalized field is traced to source facts or a named derivation.
- All transform and mapping parameters are versioned and hashed.
- Source facts, adapter-derived facts, operator rules, and Metriplane results stay
  in separate trust layers.
- The portable fixture includes a complete checksum inventory.
- The adapter produces the same fixture from the same inputs on repeated runs.

## Gate D: Metriplane execution

Required:

- The portable fixture passes contract validation.
- The normalized session uses the declared FrameStateModel version.
- The domain pack contains only operator-configured process rules.
- Repeated runs produce the same event and incident result.
- Any evidence bundle verifies successfully.
- Any generated regression executes successfully.
- A no-incident result does not fabricate incident artifacts.

## Gate E: review and closure

Required:

- The nominated reviewer can inspect the source mapping and process rule.
- Missing data and deviations are recorded, not inferred later.
- The final report names what was and was not evaluated.
- Attribution and publication permissions are recorded separately.
- A negative result remains publishable internally and payable when compensation
  was agreed.

## Completion record

The final record should include:

- Exact source, revision, and selection.
- Adapter identity and parameters.
- Metriplane version and commit.
- Fixture fingerprint and checksums.
- Process rule identity.
- Outcome classification.
- Event, deviation, and incident counts.
- Evidence and regression results, when applicable.
- Reviewer action and date.
- Limitations and publication permissions.
