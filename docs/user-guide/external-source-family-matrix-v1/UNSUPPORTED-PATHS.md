<!--
SPDX-FileCopyrightText: 2026 Miko Parkkinen
SPDX-License-Identifier: MIT
-->

# Negative-result and unsupported-path register

| Path | Decision | Why it is not a proven compatibility path | What exists |
| --- | --- | --- | --- |
| CALVIN | `NO-GO` | No dataset-specific public redistribution grant for derived state and no authoritative per-sample clock or official exact fixed-step guarantee | One documentation-only Phase-0 audit; no adapter, fixture, conversion, Atlas run, evidence bundle, regression, or portability result |
| MimicGen | `PARTIALLY SUPPORTED` | Identity and rights were partially inspected, but no immutable raw/prepared human-source chain, artifact-specific clock proof, or HDF5 body audit was completed | A bounded partial comparison record; no adapter, fixture, conversion, Atlas run, or compatibility proof |
| RoboCasa / RoboCasa365 | `NOT TESTED` | The family was not inspected after robomimic satisfied the ordered source selection | No source identity, rights decision, clock, field map, adapter, fixture, or result |
| ROS 2 / MCAP + TF2 | `NOT TESTED` | Future work has not selected one immutable recording, semantic profile, clock, frame path, or identity/completeness policy | No ROS 2 or MCAP compatibility claim |
| MassRobotics AMR offline replay | `PARTIALLY SUPPORTED` | Synthetic offline records; live transport and real recordings are outside the profile | Deterministic incident/control replay with verified incident evidence and regression |
| ManiSkill beyond the pinned PickCube path | `NOT APPLICABLE` to the `GO` row | The proof covers one episode, two normalized fixtures, and one operator scenario | Any broader task, dataset, field, platform-conversion, or semantic claim needs a new audit |
| robomimic beyond the pinned Can path | `NOT APPLICABLE` to the `GO` row | The proof covers one 118-frame trajectory and one position-only operator scenario | Other tasks, episodes, prepared fields, formats, and HDF5 files are not covered |

The CALVIN rejection is an intended contract outcome: two independent Phase-0
gates prevented an unsupported fixture from being manufactured. It must not be
counted as compatibility, portable evaluation, or an Atlas result.

No missing cell in this register is filled by analogy. Storage format, source
project lineage, or simulator ancestry does not transfer semantics, rights,
clock authority, frames, units, identity, or completeness from one row to
another.

The MassRobotics row is limited to its selected identity/status fields. Real
recordings, other entities, path normalization, additional datums or units,
non-identity transforms, live transport, fleet behavior, safety, and ISO 21423
remain outside the profile.
