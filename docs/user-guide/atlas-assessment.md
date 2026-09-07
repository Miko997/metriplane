<!--
SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Understand requirement outcomes and compare recorded runs

This page describes the unreleased MET-162 change on the current 0.4 release
line. The published `0.4.0.post2` wheel does not contain these assessment and
comparison guards. A successful command means the recorded input was processed;
zero incidents alone does not establish that every requirement was satisfied.

## Read a requirement outcome

New runs retain `requirement_assessment.json` and show its outcomes in the
Incident Report. Each process step has one of four outcomes:

| Outcome | Meaning under the recorded-sample policy |
| --- | --- |
| `satisfied` | The step completed and no delay deviation was emitted for it. |
| `violated` | A delay deviation was emitted; later completion does not erase it. |
| `unresolved` | The step activated but the recording ended before completion, without an emitted delay deviation. |
| `not_exercised` | The step never activated, including a later step that the sequential process never reached. |

A run is `violated` if any step is violated, otherwise `unresolved` if any step
is unresolved, otherwise `not_exercised` if any step is not exercised, otherwise
`satisfied`. Per-step completion timestamps remain available when a violated
step later completes. Coverage gaps are reported separately from these outcomes;
a completed step does not make an incomplete recording complete.

## Understand the timing policy

The explicit policy identifier is `legacy_sampled_missing_v1`. This change
preserves the existing detector and its events:

1. Each supplied sample uses `ts_sim_ns` converted to seconds when present,
   otherwise `ts`. Samples do not establish what happened between them.
2. The first eligible observation activates a step. Required-asset presence and
   completion are checked before the missing-state threshold at each sample.
3. While an asset is missing, the detector emits a delay when its existing
   binary floating-point elapsed time is at least `max_wait_s`.
4. Changing the first missing required asset resets that asset's absence timer.
   The assessment preserves all such episodes and any earlier violation.
5. If the trigger disappears or becomes ineligible while pending, the legacy
   timer remains; the assessment marks the observation gap.

Consequently, an arrival first observed exactly at the threshold completes
without a delay. An arrival first observed after the threshold can also complete
without a delay if no eligible missing sample previously emitted one. That case
is still `satisfied` **under this sampled policy**, with the explicit note
`arrival_observed_after_threshold_without_sampled_violation`. It is not proof
that the physical arrival met a continuous-time deadline. Introducing a stricter
arrival-deadline detector would require a separate policy and compatibility change.

The assessment records activation, completion, last evaluation, each missing
episode's threshold time and actual detection time, observed sample intervals,
and coverage notes. Display durations use decimal differences of serialized
timestamps; these calculations do not change the legacy detector's arithmetic.

## Use the right wait measurement

`process_assessment.steps[].observed_wait_s` measures activation to observed
completion. A pending interval has a separate `observed_wait_lower_bound_s`;
an unexercised step has neither a measured wait nor an invented zero.

The run-level `observed_wait.total_s` is available only when all steps completed
with sufficient retained observations. Otherwise it is `null`; individual
observed intervals remain inspectable. This total sums the sequential process
steps and is not a claim about physical cycle time outside the recording.

Existing `metrics.json` values in `wait_time_s`, and the legacy wait fields in a
comparison, retain their previous values. They represent sampled deviation
durations, not total observed wait or detection latency. A control can have
nonzero observed wait and an empty legacy deviation metric.

## Compare like-for-like runs

```bash
metriplane atlas improvement compare \
  --before-run before-run \
  --after-run after-run \
  --out comparison.json
```

Check `eligibility.status` before interpreting a numerical delta:

| Status | Meaning |
| --- | --- |
| `eligible` | Both runs retain complete supported assessments under the same comparison conditions. |
| `incompatible` | Supported assessments have different process rules or other comparison conditions. |
| `insufficient_evidence` | An assessment is missing, unsupported, altered, or incomplete; this takes precedence if conditions also differ. |

Conditions include process rules and step identities, asset and workspace
mapping, work orders, contracts, evaluator version and implementation hashes,
normalization and adapter declarations, clock origin and full observed sample
schedule, initial relevant object zones, source backends, and authoritative
object collections. Every relevant entity
must have a retained position and zone observation in each sample; frame IDs
must be contiguous and the evaluation clock must strictly increase for comparison.
These are conservative comparison guards, not a new rejection policy for all
native Atlas input. Sparse historical native runs remain readable and runnable.
An instantaneous required-asset completion in the first sample lacks preceding
observation coverage. Cropping away an earlier wait or translating timestamps
does not establish an improvement. Compare aligned recording windows and initial
conditions; the tool does not infer or silently normalize their alignment.

Identical recordings evaluated with a looser threshold are not evidence of an
improved process. This includes the historical ManiSkill and robomimic
incident/control pairs whose observations are identical and whose rules differ.
Conversely, a faster observed arrival under fixed rules can be compared when both
recordings meet the coverage conditions.

For eligible runs, `comparison_status` is `improved` only if observed wait
decreases and incident count does not increase. Fewer incidents with identical
observed wait receive the descriptive status `incident_count_reduced`, without
an overall improvement claim: the legacy floating-point threshold can be
sensitive to the timestamp at which an episode starts. The symmetric
`incident_count_increased` status describes more incidents with unchanged wait.
Opposing changes are a `tradeoff`; equal measurements are `unchanged`; increased
wait with no incident reduction is `regressed`. Ineligible runs are
`not_comparable`, with explanatory reasons
and no observed-wait delta used for an improvement conclusion. Even an eligible
comparison does not establish causation, adoption, safety, or economic impact.

## Artifact compatibility and integrity

The outer artifact schema is `metriplane.atlas.run_assessment.v1`; its
`process_assessment` uses `metriplane.atlas.requirement_assessment.v1`.
`atlas_manifest.json` references the file through
`artifacts.requirement_assessment` and the optional
`requirement_assessment_sha256`. The assessment binds retained inputs and
evaluation outputs through `evidence_sha256`. Reading it verifies the hashes
and reconstructs the comparison context from retained files. Producer identity
is compared as recorded, so upgrading a reader does not silently relabel a run.

New incident bundles include the assessment in their checksum inventory.
Bundle verification detects changed assessment bytes, and existing incident
replay and regression semantics are preserved. Bundle checksums establish
retained-file integrity, not author authentication or upstream physical accuracy.
The assessment describes the complete source run; a bundle's event timeline
remains the incident-specific excerpt.
The verifier also checks the assessment's state/configuration hashes against
the files actually bundled. Custom-segment export remains supported: if the
exported state differs from the full source run, its assessment is omitted and
the copied report and limitations explicitly state that the source-run outcomes
do not assess the custom segment.

Old manifests and bundles remain readable. An old run without assessment
metadata receives `insufficient_evidence` when compared; no context or success
is guessed. Re-evaluate preserved inputs into a fresh output directory to obtain
new metadata. Never rewrite old evidence or relabel a published artifact.
The strict `metriplane.external_run_summary.v1` JSON shape is unchanged; obtain
the assessment reference from the run's `atlas_manifest.json`.
