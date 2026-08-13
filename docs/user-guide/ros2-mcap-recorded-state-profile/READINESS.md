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
| Original ROS 2/MCAP adapter freeze | `04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` |
| Effective hardened ROS 2/MCAP adapter freeze | `686c38c2f8ca34439f851b5d62c8f7cd1cfddac8` |
| Capability schema SHA-256 | `30f42190171f9adcc51387909b738378143821c624187604a6d8d89256f103da` |
| SDK lock SHA-256 | `bc2aee5afdd495b57238a03e450beac1ee9344cadd1657cd6f8d8df746fcd1de` |
| Synthetic source | 28,735 bytes; SHA-256 `c61100bb3c95fffa436043f82e1674faeb693d918cee52d14177b485a5076e99` |
| Frozen config SHA-256 | `a984825975fcdc62f2b8599f6ecf76667da3f055cb61ffab0ba9bee7b2541962` |
| Adapter lock SHA-256 | `864f24f57d1e99ecae76e7da832c8022bbfcbaf0583b612e6d909a5e93f4edd6` |
| Native capability record file | `563fca13873a90d79644c9b5f552c3377e6f0143ead46403beb13fa5aa037295` |
| Native capability fingerprint | `ef9341324267b53ce94fa17b6eb313c1d839b2062ed26b9c0ee93a046bfe307f` |
| Shared session SHA-256 | `4404c092ef1d8940a115c68bcfde4f8f0ac1065a968aaa7e318f3fa8c61d2ee8` |
| Incident fixture fingerprint | `b88fe8731b3d9ed63414b6bd3d4af8be0d68e8259ed6c467fbf9df63e2bece66` |
| Control fixture fingerprint | `2d7b98ffba20bd91b13c8ee311bacf9365b64d8dd5b56b8eaa1898226c3c9062` |
| Generated fixture inventory file | SHA-256 `37709e9e02307fb17e87c3bac27f14808608da5cdeec567277fddf71f8c790de` |
| Conversion summary | SHA-256 `2c97916ad90a3c89387a964b5d7f35022593147b3566ccc3fffd7f260c4c4892` |
| Three-run conversion tree | SHA-256 `c010d56b587f2100eb79b35bb448fe24c07231871b992e368a5552844ff0f14d` |
| Green review-evidence commit | `a67d98c12691f2981344d68cd5ace075735b129e` |
| Reviewed PR head before additive corrections | `8da65e01c1dfe72dd03340e798a1d691250ed529` |
| Pull request | `https://github.com/Miko997/metriplane/pull/57` |

The reviewed PR head `8da65e01c1dfe72dd03340e798a1d691250ed529`
completed these public workflow runs:

| Workflow | Run | Result |
| --- | ---: | --- |
| Bounded ROS 2 and MCAP Recorded-State Profile | `31680068755` | pass |
| CI | `31680068746` | pass |
| Release Gates | `31680068824` | pass |
| Documentation | `31680068784` | pass |
| CodeQL | `31680068749` | pass |
| External Source-Family Matrix | `31680068821` | pass |
| robomimic Low-Dimensional Fixture | `31680068744` | pass |

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
- [x] The isolated adapter suite passes 115 tests.
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
`04090e510fa2bccd4fe3ac90521d3201a7c1b7c7` and the additive hardened freeze
`686c38c2f8ca34439f851b5d62c8f7cd1cfddac8` in public history. No merge, tag,
release, DOI, package release, or version bump is authorized by this record.

The branch is ready for owner merge review while the result remains PARTIAL. An
optional immutable synthetic proof identity may be proposed later, but it must
not imply external ROS 2 or MCAP compatibility.
