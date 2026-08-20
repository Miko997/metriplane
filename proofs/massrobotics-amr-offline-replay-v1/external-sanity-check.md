<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Prepared external sanity-check package

Status: **prepared, not sent**

Pull request: <https://github.com/Miko997/metriplane/pull/74>

Mapping note:
[`docs/specs/massrobotics-amr-offline-replay-profile-v1.md`](../../docs/specs/massrobotics-amr-offline-replay-profile-v1.md)

## What is being reviewed

This is one owner-generated, bounded offline mapping from two independently
authored synthetic identity/status streams to Metriplane FrameStateModel `1.0`,
followed by an unchanged Atlas evaluation. The source description is:

> Metriplane-authored synthetic MassRobotics-format engineering fixture

The upstream MassRobotics AMR Interoperability Standard Version `1.0` and
official post-release snapshot
`f9357a423ecabc3f7112e6d10025a5231943ec50` are reference-only. No upstream
schema, PDF, official example, sender, or receiver file is included.

## Small synthetic source excerpt

This abridged, Metriplane-authored excerpt shows only the current-location
fields relevant to the question. It is not a complete converter input and is
not copied from an official example.

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

AMR 1's optional frame-0 path has one predicted point with no
`planarDatumUUID` and one with the same datum explicitly. Those points are
validated only; neither can create a frame, replace a current observation, or
trigger Atlas.

## Incident and control summary

Both variants contain two identities, 18 current-status records at nine exact
one-second timestamps, and nine complete normalized frames with two objects
each. Metres and the identity transform are explicit fixture-specific operator
configuration.

| Variant | Rendezvous timing | Atlas result | Incident-derived artifacts |
| --- | --- | --- | --- |
| Incident | AMR 1 enters at `2.0 s`; AMR 2 is outside at the `5.0 s` deadline and enters at `6.0 s` | 4 events, 1 deviation, 1 `missing_tool_caused_delay` incident | Evidence bundle verifies; generated regression passes |
| Control | AMR 1 enters at `2.0 s`; AMR 2 enters at `4.0 s`, before the deadline | 3 events, 0 deviations, 0 incidents | None; verification and regression are N/A |

The adapter performs no carry-forward, interpolation, resampling, cross-datum
transform, prediction-to-observation promotion, or source-event generation.

## Deliberate limitations

- synthetic current-status data only; no external or production recording;
- exactly two process-relevant AMRs in complete snapshots;
- one expected planar datum, identity transform, and operator-configured metre
  binding;
- current location only; paths and destinations remain predictions;
- no live transport, MQTT, WebSocket, QoS, retained-message, or session
  reconstruction;
- no fleet management, dispatch, planning, robot control, or safety function;
- no general MassRobotics compatibility, conformance, certification,
  organizational validation, adoption, or endorsement; and
- no ISO 21423 implementation or conformance claim.

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

A neutral or critical answer is useful. This request seeks a semantic sanity
check, not endorsement, certification, a positive conclusion, or permission to
make broader claims. No private correspondent is named and no private
correspondence is quoted.
