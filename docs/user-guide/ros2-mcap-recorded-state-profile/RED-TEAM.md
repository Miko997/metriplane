<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Red-team record

## Review result

**PARTIAL / synthetic-only boundary preserved.**

| Question | Finding |
| --- | --- |
| Are storage semantics being called interoperability? | No. MCAP parsing is only format engineering. No external recording passed semantic gates. |
| Is the evaluation clock authoritative? | Yes only for the authored synthetic source. `PoseStamped.header.stamp` is declared authoritative by its author. |
| Is the clock domain explicit? | Yes, synthetic `ROS_TIME`. The candidate recordings were rejected where official evidence did not establish it. |
| Are log and publish time separated from message time? | Yes. Both remain provenance and have verified offsets. |
| Are source and adapter-derived fields separated? | Yes. Decoded source fields, transforms, IDs, projection, zones, and rules have distinct provenance. |
| Is materialized state being called raw? | No. Complete-snapshot joining, transform composition, projection, and zones are adapter-derived. |
| Is every position tied to a frame? | Yes. Both pose streams declare `sensor_frame` and use the exact static path to `world`. |
| Is every unit authoritative? | Yes for the synthetic source, whose channel metadata and config declare metres. No unit is inferred from magnitude. |
| Is TF resolution deterministic? | Yes. Exactly two ordered static edges are accepted. |
| Is interpolation hidden? | No. It is unsupported and rejected. |
| Is carry-forward hidden? | No. It is unsupported and rejected. |
| Can missing observation become physical absence? | No. Missing required state rejects the recording. |
| Is identity stable? | Yes. Two configured channel metadata identities map one-to-one to normalized IDs. |
| Can message order become entity identity? | No. Sequence is structural validation only. |
| Can source result labels influence Atlas? | No. Outcome fields are excluded and covered by mutation/deletion tests. |
| Are operator rules separate from source truth? | Yes. Polygon, roles, required asset, and waits are Layer C. |
| Are recording rights proven? | Only for the Metriplane-authored synthetic source. External candidates did not pass the required boundary. |
| Are normalized-derived-state rights proven? | Yes for the Metriplane-authored synthetic fixture. No external derivative is published. |
| Does the ordinary wheel remain source-neutral? | Yes. Reviewed exact-head wheel inspection found no SDK, MCAP, CDR, ROS schema, or adapter dependency; the live pull request is authoritative for later additive heads. |
| Does evaluation require ROS? | No for the finalized portable fixture. The reviewed installed-wheel matrix passed all four Ubuntu/macOS and Python 3.12/3.13 rows. |
| Do three conversions agree? | Yes. Three clean conversions are byte-equivalent with conversion-tree digest `c010d56b587f2100eb79b35bb448fe24c07231871b992e368a5552844ff0f14d`. A raw single conversion remains `not_demonstrated`; only finalization promotes the capability to verified. |
| Do all OS and Python rows agree? | Yes. Ubuntu and macOS passed on Python 3.12 and 3.13 for the reviewed exact head; the live pull request governs later additive heads. |
| Can another engineer acquire the exact external source? | Immutable candidate identities are documented, but no candidate is an accepted source. The synthetic source is generated from the frozen adapter. |
| Are machine-local paths absent? | Yes. Local and reviewed exact-head converter, finalized-package, relocation, wheel, and ZIP scans passed; the live pull request governs later additive heads. |
| Can publication race the validated candidate or inputs? | The hardened Linux converter descriptor-binds the complete candidate and parent, uses atomic no-clobber publication, rechecks the published tree and source/config/lock/Git identities, and rolls back on mismatch. Existing destinations fail closed. The guarantee is point-in-time, not protection from a same-privilege writer after return. |
| Does wording imply general ROS 2 or MCAP support? | No. The result is consistently labeled synthetic format engineering and PARTIAL. |
| Were earlier fail-closed gates weakened? | No. The absence of an accepted source preserves those gates. |
| Does the SDK contain ROS-only fields? | No. Topics, channels, schemas, and TF paths stay in adapter configuration and provenance. |
| Does the SDK reduce repeated work? | Yes. It consolidates identity, rights, clock, coordinate, completeness, provenance, anti-taint, determinism, isolation, portability, and claim checks. |
| Could a second recording reuse the profile without Atlas changes? | Plausibly, but only after it passes a separate source audit and matches the explicit profile. This has not been demonstrated. |
| What falsifies the claim? | Any source, schema, clock, TF, materialization, identity, deterministic-output, portability, anti-taint, or evidence mismatch falsifies the bounded format-engineering result. |

## Adversarial conclusion

The strongest defensible statement is that a small source-neutral capability
layer and one narrow synthetic ROS 2/MCAP recorded-state profile have been
engineered without changing Metriplane core semantics. No external ROS 2/MCAP
recording has passed the contract.
