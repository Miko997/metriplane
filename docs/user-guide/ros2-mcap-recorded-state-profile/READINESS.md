<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Readiness record

## Current decision

**PARTIAL: READY FOR OWNER MERGE REVIEW**

The bounded external-source search is complete. Three candidates were rejected
and no external source was selected. The synthetic format-engineering artifacts
have immutable implementation and generated-output identities. They do not
establish external ROS 2 or MCAP compatibility.

## Immutable identities

| Item | Exact identity |
| --- | --- |
| Starting public main | `f8a3a48752101d74f658124e23354f0816e20a21` |
| Candidate audit commit | `782712f8b87c5daf237b55101594dcf91abed103` |
| Source Adapter SDK commit | `975fda022962b9f1f6a1b986693557600a320916` |
| ROS 2/MCAP adapter freeze | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |
| Capability schema SHA-256 | `30f42190171f9adcc51387909b738378143821c624187604a6d8d89256f103da` |
| SDK lock SHA-256 | `bc2aee5afdd495b57238a03e450beac1ee9344cadd1657cd6f8d8df746fcd1de` |
| Synthetic source | 28,735 bytes; SHA-256 `c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99` |
| Frozen config SHA-256 | `a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962` |
| Adapter lock SHA-256 | `864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6` |
| Native capability record file | `18b2ceb08568aaf3975d3bdf87354d182d93551625f5e8b59a25cd4aa36ba27d` |
| Native capability fingerprint | `3bb37c0457a945fbea166e339d57c373e8251620f3a90ec3a02992fec7b01db7` |
| Shared session SHA-256 | `4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8` |
| Incident fixture fingerprint | `79d1061df5e4f8880f29ead31de3dfac8adae5cf52fbe269513cb6beeb67ae31` |
| Control fixture fingerprint | `559f9c803da6514c82c4ee83c2b925d505be88db2a57582daf7e1d82ec68db42` |
| Generated fixture inventory file | SHA-256 `0a3dd86c91e2c5a78a3fbafcfdaad6d6de7e1669812f99968f8e73626d2726de` |
| Conversion summary | SHA-256 `bff6ff0456178798bd3d987f3c3a687b900aa0c511e571b72d06503765067218` |
| Three-run conversion tree | SHA-256 `56a70b440f3105ae01a2913940db664008a829dae05d4442dc610aaa99b80505` |
| Green review-evidence commit | `a67d98c12691f2981344d68cd5ace075735b129e` |
| Pull request | `https://github.com/Miko997/metriplane/pull/57` |

The green review-evidence commit completed these public workflow runs:

| Workflow | Run | Result |
| --- | ---: | --- |
| Bounded ROS 2 and MCAP Recorded-State Profile | `31679707210` | pass |
| CI | `31679707212` | pass |
| Release Gates | `31679707236` | pass |
| Documentation | `31679707484` | pass |
| CodeQL | `31679707205` | pass |
| External Source-Family Matrix | `31679707220` | pass |
| robomimic Low-Dimensional Fixture | `31679707195` | pass |

The pull request's live head must also retain a complete green exact-head suite.
Workflow status remains live review metadata rather than a self-referential
property of this hashed file.

## Stable boundaries

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

## Completed local gates

- [x] Exactly three official external candidates have immutable audit records.
- [x] Every candidate has a hard-gate rejection reason.
- [x] No candidate recording is used for conversion.
- [x] Public wording remains PARTIAL and synthetic-only.
- [x] The capability schema and all three capability records validate.
- [x] The isolated SDK suite passes 146 tests.
- [x] The isolated adapter suite passes 101 tests.
- [x] Three clean synthetic conversions are byte-equivalent.
- [x] Frozen generated-fixture inventories validate.
- [x] Incident output is `60/4/1/1`; evidence verifies and regression passes.
- [x] Control output is `60/3/0/0`; the no-incident assertion passes.
- [x] Durable generated outputs contain no machine-local paths.

## Completed public and repository gates

- [x] frozen fixture assertions on the review-evidence commit;
- [x] full repository regression and existing proof-family tests;
- [x] source-family matrix validation, bundled demo, documentation, release
      gates, and applicable static checks;
- [x] ordinary wheel contents and source-dependency isolation;
- [x] installed-wheel portable evaluation on Ubuntu and macOS with Python 3.12
      and 3.13;
- [x] exact frozen synthetic-source acquisition, inspection, three-conversion,
      and finalization check;
- [x] all other applicable review-evidence workflows;
- [x] public review-evidence commit and workflow identities recorded.

No real-source conversion job can run because no external candidate passed the
bounded audit. The green exact-source job reproduces only the Metriplane-authored
synthetic format-engineering source. It is not a successful external conversion.

## Merge boundary

Any eventual merge must preserve the adapter freeze commit
`04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` in public history. No merge, tag,
release, DOI, package release, or version bump is authorized by this record.

The branch is ready for owner merge review while the result remains PARTIAL. An
optional immutable synthetic proof identity may be proposed later, but it must
not imply external ROS 2 or MCAP compatibility.
