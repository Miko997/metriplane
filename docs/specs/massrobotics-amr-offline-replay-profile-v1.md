<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# MassRobotics AMR offline-replay profile v1

Profile ID: `metriplane.massrobotics_amr_offline_replay.v1`

## Purpose and profile scope

This profile demonstrates one bounded, local, offline conversion of two
Metriplane-authored identity/status streams into External Source Contract v1
fixtures and unchanged FrameStateModel `1.0` input. Atlas then evaluates one
operator-authored two-AMR rendezvous deadline. The incident and control variants
use the same identities, clock, coordinate binding, workspace, and process
rule; only the required AMR's recorded trajectory differs.

The isolated package is `metriplane-massrobotics-amr-adapter`, adapter ID
`org.metriplane.massrobotics_amr_offline_replay`, module
`massrobotics_amr_adapter`, and CLI `metriplane-massrobotics-amr`. It is not an
ordinary Metriplane runtime dependency.

The source is a **Metriplane-authored synthetic MassRobotics-format engineering
fixture**. The records were written for this profile and are not derived from a
robot recording or an official example. The profile covers offline current-state
replay only.

## Practical relevance

Discussing offline replay of multi-vendor AMR status data, Zachary Dydek offered
the following personal perspective:

> “I expect that people will want to build dashboards for live (and replay)
> views of deployed AMR fleets from multiple vendors.”

— Zachary Dydek, Ph.D., speaking in a personal capacity (August 2026; quoted
with permission).

This observation identifies a potential use case. It does not constitute
Metriplane adoption, technical validation, conformance, or endorsement by any
organization.

## Frozen reference identity and rights

The referenced interoperability specification is the MassRobotics AMR
Interoperability Standard Version `1.0`, release commit `7161a0d`
(`7161a0d2b26606941f5a012cd03c7f113beb7a22`). The official
post-release repository snapshot is commit
`f9357a423ecabc3f7112e6d10025a5231943ec50`. At that snapshot the recorded Git
blob identities are:

| Repository path | Git blob |
| --- | --- |
| `AMR_Interop_Standard.json` | `7ba8974ae46d81ea0f6f8ed0ac7899d9d279af98` |
| `AMR_Interop_Standard.pdf` | `2436fee76da3a7b15516b518d85d237724925f90` |
| `README.md` | `4031260c9036672a6cd85b93111862b5daa568c3` |
| `examples/identityReport1.json` | `112ac8d1df62170f785dadf03419968c7e8b61df` |
| `examples/statusReport1.json` | `b396acbf743c2ffcd448dd675dc830b77384b054` |

These upstream materials are reference-only and are represented by immutable
identifiers rather than stored files. The complete URL register is in
`proofs/massrobotics-amr-offline-replay-v1/source-identity.json`,
and the artifact-scoped decision is in
`proofs/massrobotics-amr-offline-replay-v1/rights-decision.md`.
The independently authored synthetic records and their portable normalized
fixtures are MIT-licensed under the repository's normal notices.

## Bounded mapping

Two stable source UUIDs become two `ObjectStateModel.id` values in configured
order. Identity fields establish the bounded entity registry. Each status UUID
must match it. Status timestamps group complete two-AMR snapshots. Current
`location.x`, `.y`, and explicit `.z` become `pos_world`; current
`location.planarDatum` is validated as the authoritative datum. The current
quaternion is validated but not normalized. The adapter derives deterministic
frame IDs, elapsed time, zone labels, and an empty `events` list. It does not
emit confidence, source-generated events, inferred state, `fused`, or
`raw_per_camera` data.

Source-conversion provenance remains separate from later Metriplane
run/config/git provenance. Evaluation provenance never becomes a source fact.

| Frozen fixture fact | Value |
| --- | --- |
| AMR 1 UUID | `11111111-1111-4111-8111-111111111111` |
| AMR 2 UUID | `22222222-2222-4222-8222-222222222222` |
| Planar datum UUID | `aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa` |
| Identity timestamp | `2026-08-20T09:59:59Z` |
| Current-status timestamps | `2026-08-20T10:00:00Z` through `10:00:08Z`, exact 1 s interval |

The fixture-specific operator binding is:

| Setting | Value |
| --- | --- |
| Source linear unit | `m` |
| Target linear unit | `m` |
| Target frame | `metriplane_world` |
| Transform | identity |
| Unit authority | `operator_configured_fixture_binding` |

The metre binding is a fixture-specific operator interpretation. The rendezvous polygon is
`[(4,-1), (6,-1), (6,1), (4,1)]`, with the External Source Contract v1 polygon
implementation, inclusive boundary, overlap rejection, and
`outside_workspace` outside label. Zone assignment is adapter-derived from the
operator rule, not source truth.

Atlas maps the two UUIDs to `amr_1` of type `rendezvous_trigger_amr` and
`amr_2` of type `rendezvous_required_amr`. The sole step requires `amr_2` in
`rendezvous_zone` / `rendezvous_station` no more than `3.0 s` after `amr_1`
enters. This operator-authored engineering rule is separate from the source
records and referenced standard. The exact field-to-trust-layer mapping is in
`proofs/massrobotics-amr-offline-replay-v1/mapping-table.json`.

## Clock, datum, prediction, and completeness policies

Source timestamps require `Z` or an explicit UTC offset. Naive timestamps and
more than nine fractional-second digits are rejected; zero through nine digits
are accepted and nanoseconds are preserved deterministically after UTC
normalization. The first status timestamp is evaluation origin. The earlier
identity timestamp is provenance, not a frame. Source order must be monotonic;
the adapter does not sort. Duplicate `(uuid, timestamp)` records, conflicting
duplicates, non-1-second fixture gaps, interpolation, resampling, and
carry-forward are rejected.

Every current location must carry the configured datum UUID. A missing,
malformed, changed, or cross-entity datum rejects conversion. A path point may
omit its datum and inherit the current datum for validation only, or state the
same datum explicitly. A different path datum rejects conversion. Even a
requested explicit transform is outside v1: only the identity binding is
accepted, and no transform registry exists. A missing coordinate binding, an
unknown or unsupported unit, or a requested non-identity transform also
rejects conversion.

The optional frame-0 path is prediction-validation coverage only. Predicted
timestamps, poses, and inherited/matching path datums are parsed and validated,
but never create frames, replace current locations, cause zone entry, trigger
Atlas, or appear as observed positions.

Each of the nine normalized frames must contain both process-relevant AMRs.
Missing status means **source snapshot incomplete** and rejects before Atlas. It
never means absent, unchanged, outside the zone, or offline.

## Information loss and result

Identity manufacturer, model, serial, and base envelope, plus status
operational state, validated orientation, scalar velocity, battery, remaining
runtime, load, error codes, destinations, and path are retained or summarized
only as provenance. Orientation is not normalized; scalar speed is not
fabricated as Cartesian `vel_world`; predictions remain predictions. Battery,
errors, and operational state cannot affect Atlas incident truth.

Local executable proof on the MET-55 branch verified these results:

| Fixture | Identities / timestamps / records | Frames / objects each | Atlas events | Deviations / incidents | Incident artifacts |
| --- | --- | --- | --- | --- | --- |
| Incident | `2` / `9` / `18` | `9` / `2` | `4` | `1` / `1` | verified bundle; passing regression |
| Control | `2` / `9` / `18` | `9` / `2` | `3` | `0` / `0` | none (verification/regression N/A) |

The incident sequence is `required_asset_missing` at `2.0 s`, `step_delayed`
at `5.0 s`, then `required_asset_present` and `step_completed` at `6.0 s`. It
produces the existing Atlas incident type `missing_tool_caused_delay`. The
control sequence is `required_asset_missing` at `2.0 s`, then
`required_asset_present` and `step_completed` at `4.0 s`. Conversion-time
events, carry-forward operations, interpolation operations, cross-datum
transforms, and prediction-derived frames are all zero.

## Reproduce and limitations

Run the isolated conversion and source-neutral fixture commands exactly as
documented in
`proofs/massrobotics-amr-offline-replay-v1/REPRODUCE.md`.
The incident bundle alone is verified with `metriplane atlas bundle verify` and
its generated regression is executed with `metriplane atlas test`. A control
run must not manufacture either artifact.

From the intended exact, clean checkout, capture its commit before running the
commands:

```console
export MET55_COMMIT="$(git rev-parse HEAD)"
test -z "$(git status --porcelain)"
metriplane external validate examples/external_sources/massrobotics_amr/incident
metriplane external validate examples/external_sources/massrobotics_amr/control
METRIPLANE_GIT_COMMIT="$MET55_COMMIT" metriplane external run examples/external_sources/massrobotics_amr/incident --out incident-run --run-id massrobotics_amr_incident
METRIPLANE_GIT_COMMIT="$MET55_COMMIT" metriplane external run examples/external_sources/massrobotics_amr/control --out control-run --run-id massrobotics_amr_control
metriplane atlas bundle verify incident-run/evidence_bundles/INC-0001.zip
metriplane atlas test incident-run/regression_tests/INC-0001.yaml
```

The profile covers two complete synthetic current-status streams, one datum,
one operator-configured metre/identity binding, one polygon, and one deadline.
Paths, destinations, live transport, QoS, retained messages, sessions,
cross-datum transforms, fleet functions, robot control, production use, safety
use, and ISO 21423 are outside its scope. Core schemas and Atlas behavior are
unchanged.
