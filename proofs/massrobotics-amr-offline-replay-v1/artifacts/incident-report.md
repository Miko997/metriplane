# Incident Report

Formal artifact: `Cell Truth Report`.

This report summarizes one recorded run: a saved sequence of object positions and timestamps from a bounded workcell.

## What happened

- Metriplane reviewed 8.0 s of recorded activity.
- It recorded 4 events and grouped them into 1 incident.
- An event is one observed change, such as an object arriving or a required tool being absent.
- An incident groups related events that need review because an expected process condition was not met.
- Incident `INC-0001` (warning): amr 2 missing during Second AMR reaches the rendezvous zone. Second AMR reaches the rendezvous zone waited because amr 2 was absent.
- Suggested follow-up: Add a required-tool staging check. INC-0001 shows a required asset was absent while a process step waited. Add a visible pre-step tool/material check.

## Why it was flagged

Process rules describe the expected steps, required objects and locations, and allowed waiting times. Metriplane flags a deviation when the recorded run does not meet one of those rules.

| reason | severity | expected step | object | supporting event records |
|---|---|---|---|---|
| missing required asset (`missing_required_asset`) | warning | `two_amr_rendezvous` | `amr_2` | `evt_0001`, `evt_0002` |

## When it happened

The times below are measured from the start of the recorded run.

| time | what was observed | object | technical event record |
|---:|---|---|---|
| 2.0 s | amr_2 was not present for Second AMR reaches the rendezvous zone. | `amr_2` | `evt_0001` / `required_asset_missing` |
| 5.0 s | Second AMR reaches the rendezvous zone waited 3.0 s for amr_2. | `amr_2` | `evt_0002` / `step_delayed` |
| 6.0 s | Synthetic required AMR was present for Second AMR reaches the rendezvous zone. | `amr_2` | `evt_0003` / `required_asset_present` |
| 6.0 s | Second AMR reaches the rendezvous zone completed. | `amr_2` | `evt_0004` / `step_completed` |

## Evidence that was saved

An evidence bundle is a checksummed ZIP that keeps the incident report and supporting records together so another person can verify what was reviewed.
- Evidence bundle for `INC-0001`: `evidence_bundles/INC-0001.zip`
- Event records: `physical_event_log.jsonl`
- Incident records: `incidents.jsonl`
- Supporting recorded state: `state_segment.jsonl`
- Formal Cell Truth Report: `cell_truth_report.html`

## Repeatable check that was generated

A regression check is a generated test that replays the saved incident and checks that the expected events and incident still appear within declared timing tolerances.

Deterministic replay uses the saved inputs and recorded time sequence instead of live timing, so repeated evaluations can be compared consistently.
- Repeatable check for `INC-0001`: `regression_tests/INC-0001.yaml`

## External fixture provenance

- Fixture: `massrobotics_amr_synthetic_incident_v1`.
- Contract: `metriplane.external_source_contract.v1` / `metriplane.atlas.complete_snapshot.v1`.
- Source: `Metriplane synthetic MassRobotics-format engineering source` at revision `git_commit:6a24ebf1bda47860bda9c5a9bca2c0d94eb37b15`.
- Adapter: `org.metriplane.massrobotics_amr_offline_replay` version `1.0.0` at commit `6a24ebf1bda47860bda9c5a9bca2c0d94eb37b15`.
- Full conversion provenance: `external_source_provenance.json` (SHA-256 `1f0f1432aa48a3d36e39fc6f1519b3bbda51080756981b62c6f998eddc4f0b61`).
- This identifies the supplied normalized fixture and its conversion; the incident result still comes from the recorded normalized state and the supplied process rules.

## Limits of this result

- This result is derived from recorded normalized planar object state supplied for evaluation, not a fresh interpretation of raw sensor data.
- It depends on the object identities, state, zone assignments, and process rules supplied for this run.
- It does not establish correctness, calibration, physical accuracy, or simulator realism of the upstream state.
- It is not a certified safety or quality decision and does not control machinery.
- It does not prove root cause; suggested follow-ups require before-and-after validation.
