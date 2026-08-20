<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Technical review brief

Pull request: <https://github.com/Miko997/metriplane/pull/74>

Mapping note:
[`docs/specs/massrobotics-amr-offline-replay-profile-v1.md`](../../docs/specs/massrobotics-amr-offline-replay-profile-v1.md)

## Profile

The adapter maps two independently authored synthetic identity/status streams
to FrameStateModel `1.0`, then runs the existing Atlas rendezvous rule. The
source is a **Metriplane-authored synthetic MassRobotics-format engineering
fixture**. MassRobotics AMR Interoperability Standard Version `1.0` and
post-release snapshot `f9357a423ecabc3f7112e6d10025a5231943ec50` are
reference-only.

## Source excerpt

This abridged record shows the current-location fields used by the profile:

```json
{
  "location": {
    "angle": {"w": 1.0, "x": 0.0, "y": 0.0, "z": 0.0},
    "planarDatum": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "x": 4.25,
    "y": 0.0,
    "z": 0.0
  },
  "operationalState": "navigating",
  "timestamp": "2026-08-20T10:00:02Z",
  "uuid": "11111111-1111-4111-8111-111111111111"
}
```

AMR 1's optional frame-0 path contains one predicted point without
`planarDatumUUID` and one with the current datum explicitly. Both are validated
as predictions and do not become observations or frames.

## Results

Both variants contain two identities, 18 status records at nine exact
one-second timestamps, and nine complete frames with two objects each. Metres
and the identity transform are explicit operator configuration.

| Variant | Rendezvous timing | Atlas result | Incident artifacts |
| --- | --- | --- | --- |
| Incident | AMR 1 enters at `2.0 s`; AMR 2 enters at `6.0 s`, after the `5.0 s` deadline | 4 events, 1 deviation, 1 `missing_tool_caused_delay` incident | Bundle verifies; regression passes |
| Control | AMR 1 enters at `2.0 s`; AMR 2 enters at `4.0 s` | 3 events, 0 deviations, 0 incidents | None |

## Scope

- Synthetic current-status data for exactly two AMRs.
- Complete snapshots at 1 Hz with no carry-forward, interpolation, or resampling.
- One expected planar datum and an operator-configured metre/identity binding.
- Current locations are normalized; paths and destinations remain predictions.
- Live transport, session reconstruction, cross-datum transforms, fleet
  functions, robot control, production use, safety use, and ISO 21423 are
  outside the profile.

## Review questions

1. Is treating `location.planarDatum` as the authoritative datum for each
   recorded current location consistent with the intended interpretation?

2. Is it a reasonable offline-replay boundary to treat an omitted
   `predictedLocation.planarDatumUUID` as using the current location datum,
   accept an explicitly matching datum, and fail closed on an explicitly
   different datum rather than inventing a transform?

3. In this deliberately bounded current-status replay, where predictions are
   not treated as observations and transport/session semantics are not
   reconstructed, is another important MassRobotics interoperability semantic
   missing or better rejected explicitly?
