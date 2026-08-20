<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Metriplane MassRobotics AMR offline-replay proof v1

- Profile: `metriplane.massrobotics_amr_offline_replay.v1`
- Pull request: <https://github.com/Miko997/metriplane/pull/74>
- Source classification: `synthetic_format_engineering`
- Source description: **Metriplane-authored synthetic MassRobotics-format
  engineering fixture**

## Scope and result

An isolated adapter converts two independently authored, synthetic identity and
current-status streams into nine complete FrameStateModel `1.0` snapshots. An
unchanged Atlas evaluation applies one operator-authored two-AMR rendezvous
deadline. The incident variant produces four events, one deviation, one
`missing_tool_caused_delay` incident, a verified evidence bundle, and a passing
generated regression. The control produces three events, no deviation or
incident, and no incident-derived artifacts.

## Proof inventory

| File | Role |
| --- | --- |
| [`REPRODUCE.md`](REPRODUCE.md) | Exact isolated-conversion and source-neutral evaluation commands |
| [`source-identity.json`](source-identity.json) | Frozen upstream reference register and synthetic-origin distinction |
| [`rights-decision.md`](rights-decision.md) | Artifact-scoped reference-only and MIT rights decision |
| [`mapping-table.json`](mapping-table.json) | Machine-readable source-to-normalized trust-layer map |
| [`technical-review-brief.md`](technical-review-brief.md) | Compact technical review brief |
| [`../../docs/specs/massrobotics-amr-offline-replay-profile-v1.md`](../../docs/specs/massrobotics-amr-offline-replay-profile-v1.md) | Public bounded-profile note |
| [`artifacts/conversion-equivalence.json`](artifacts/conversion-equivalence.json) | Three-run byte-equivalence record for both variants |
| [`artifacts/execution-summary.json`](artifacts/execution-summary.json) | Exact validation, event, incident/control, and Atlas determinism result |
| [`artifacts/incident-report.md`](artifacts/incident-report.md) | Generated incident report |
| [`artifacts/incident-evidence.zip`](artifacts/incident-evidence.zip) | Verified incident evidence bundle |
| [`artifacts/incident-regression.yaml`](artifacts/incident-regression.yaml) | Generated passing incident regression |
| [`artifacts/incident-regression-portable.yaml`](artifacts/incident-regression-portable.yaml) | Semantically identical regression with only `source_bundle` rebound to the colocated durable bundle |
| [`artifacts/bundle-verification.json`](artifacts/bundle-verification.json) | Sanitized bundle verifier result |
| [`artifacts/regression-result.json`](artifacts/regression-result.json) | Sanitized generated-regression result |
| [`artifacts/privacy-provenance-checks.json`](artifacts/privacy-provenance-checks.json) | Durable-output and ZIP-member boundary checks |
| `CHECKSUMS.sha256` | Final sorted proof inventory |

The portable incident and control fixtures live under
`examples/external_sources/massrobotics_amr/`. The original synthetic source
records live under `adapters/massrobotics_amr/source/`; no official upstream
file is stored anywhere in this proof.

## Exact results

Local executable verification reproduced both exact event sequences, verified
the incident bundle, passed the generated incident regression, confirmed the
control artifact absences, and passed three-run Atlas determinism for each
variant.

| Variant | Identities | Status timestamps / records | Frames / objects each | Events | Deviations | Incidents | Bundle / regression |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Incident | 2 | 9 / 18 | 9 / 2 | 4 | 1 | 1 | produced and PASS / produced and PASS |
| Control | 2 | 9 / 18 | 9 / 2 | 3 | 0 | 0 | not produced / not produced |

Incident events are `required_asset_missing` at `2.0 s`, `step_delayed` at
`5.0 s`, and `required_asset_present` plus `step_completed` at `6.0 s`.
Control events are `required_asset_missing` at `2.0 s`, and
`required_asset_present` plus `step_completed` at `4.0 s`.

Both variants have zero conversion-time events, carry-forward operations,
interpolation operations, cross-datum transforms, and prediction-derived
frames. The control's bundle verification and regression execution are N/A,
because no such artifacts may be produced without an incident.

## Scope and rights

The upstream standard, schema, PDF, README, official examples, sender, and
receiver are represented only by immutable references. The fixture bytes are
Metriplane-authored and MIT-licensed. The metre binding, identity transform,
polygon, Atlas assets, station, and deadline are operator configuration.

The profile is limited to the included synthetic two-AMR current-state replay.
Live transport, cross-datum transforms, fleet functions, robot control,
production use, safety use, and ISO 21423 are outside its scope.
