<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Readiness record

## Current decision

**NOT READY: PARTIAL SYNTHETIC CANDIDATE**

The external-source result is final for this bounded search: three candidates
were rejected and no external source was selected. The synthetic engineering
artifacts are still awaiting immutable freeze identities and exact-head gates.

## Stable facts

- profile: `metriplane.ros2_mcap_recorded_state.v1`;
- evidence class:
  `FORMAT-ENGINEERING ONLY / SYNTHETIC / NOT EXTERNAL-SOURCE EVIDENCE`;
- external candidate decision: none accepted;
- External Source Contract: v1, unchanged;
- FrameStateModel: 1.0, unchanged;
- Atlas: source-neutral, unchanged;
- Metriplane package version: `0.3.0`;
- prior source-family matrix: unchanged;
- strongest result: PARTIAL, not GO.

## Pending immutable identities

The following values must be filled from final generated artifacts after the
adapter subtree is frozen. They are intentionally not guessed in this document:

- adapter implementation freeze commit;
- SDK schema SHA-256 and capability-record fingerprints;
- adapter lock SHA-256 and frozen-config SHA-256;
- synthetic MCAP byte size and SHA-256;
- embedded schema SHA-256 values;
- normalized shared-session SHA-256;
- incident and control fixture fingerprints;
- complete fixture inventories;
- three-conversion equivalence inventory;
- local test counts and results;
- exact PR head and exact-head workflow run identities.

## Required local gates

- [x] Exactly three official external candidates have immutable audit records.
- [x] Every candidate has an explicit rejection reason tied to a hard gate.
- [x] No candidate recording is used for conversion.
- [x] Public wording remains PARTIAL and synthetic-only.
- [ ] SDK schema and all capability records validate.
- [ ] SDK and adapter test suites pass with exact counts recorded.
- [ ] Three clean synthetic conversions are byte-equivalent.
- [ ] Frozen fixture assertions pass.
- [ ] Full repository regression, existing proof tests, matrix validation,
      bundled demo, documentation, release gates, and static checks pass.
- [ ] Ordinary wheel inspection proves dependency and source neutrality.
- [ ] Durable outputs and ZIPs contain no machine-local paths.

## Required exact-head workflows

- [ ] isolated SDK tests;
- [ ] isolated adapter and negative tests;
- [ ] frozen fixture assertions;
- [ ] portable installed-wheel evaluation on Ubuntu and macOS with Python 3.12
      and 3.13;
- [ ] real-source job is explicitly reported as not applicable because no
      external recording passed the bounded audit;
- [ ] all other applicable repository workflows are green.

## Merge boundary

Readiness can support only a normal history-preserving merge that keeps the
frozen adapter commit publicly reachable. No merge, tag, release, DOI, package
release, or version bump is authorized by this record.

If all gates pass, the branch may be ready for owner merge review with the result
still classified PARTIAL. An optional immutable synthetic proof identity may be
proposed later, but it must not imply external ROS 2 or MCAP compatibility.

